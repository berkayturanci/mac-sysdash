// sysdash menu bar companion — the fleet at a glance without a browser tab.
//
// Reads only the hub's HTTP API (/api/stats, /api/peers, /api/peer,
// /api/unreachable); it never talks to Tailscale or the runners itself. The one
// optional extra is GitHub's queued/in-progress runs via an already logged-in
// `gh` CLI — the server stays token-free, and the section is hidden without gh.
//
// Build: ./build.sh  ·  Preview: SysdashBar --snapshot out.png [--dark] [--tab N]

import AppKit
import ServiceManagement
import SwiftUI

// MARK: - Config

/// Same file the server reads (~/.config/mac-sysdash/config), so one place sets
/// the port and, for a remote hub, SYSDASH_HUB=http://<hub-ip>:8765.
enum Config {
    static let file = URL(fileURLWithPath: NSHomeDirectory())
        .appendingPathComponent(".config/mac-sysdash/config")

    static func values() -> [String: String] {
        var out: [String: String] = [:]
        if let text = try? String(contentsOf: file, encoding: .utf8) {
            for raw in text.split(whereSeparator: \.isNewline) {
                let line = raw.trimmingCharacters(in: .whitespaces)
                guard !line.hasPrefix("#"), let eq = line.firstIndex(of: "=") else { continue }
                let k = line[..<eq].trimmingCharacters(in: .whitespaces)
                let v = line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
                out[k] = v
            }
        }
        for (k, v) in ProcessInfo.processInfo.environment where k.hasPrefix("SYSDASH_") && !v.isEmpty {
            out[k] = v
        }
        return out
    }

    static var hub: URL {
        let v = values()
        if let h = v["SYSDASH_HUB"], let u = URL(string: h.hasSuffix("/") ? String(h.dropLast()) : h) {
            return u
        }
        return URL(string: "http://localhost:\(v["SYSDASH_PORT"] ?? "8765")")!
    }
}

let isTR = Locale.preferredLanguages.first?.hasPrefix("tr") ?? false
func L(_ en: String, _ tr: String) -> String { isTR ? tr : en }

// MARK: - Models (decoded loosely: /api/stats grows over time)

func num(_ v: Any?) -> Double { (v as? NSNumber)?.doubleValue ?? 0 }

struct RunnerInfo: Identifiable {
    let id: String
    let name: String
    let repo: String
    let status: String       // busy | idle | offline
    let url: String
    let jobName: String?
    let branch: String?
    let elapsed: Double?
}

struct AppUse: Identifiable {
    var id: String { name }
    let name: String
    let rss: Double
    let cpu: Double
    let procs: Int
}

struct Stats {
    let raw: [String: Any]
    private func d(_ k: String) -> [String: Any] { raw[k] as? [String: Any] ?? [:] }

    var host: String { raw["host"] as? String ?? "?" }
    var version: String { raw["version"] as? String ?? "" }
    var user: String { raw["user"] as? String ?? "" }
    var tailscaleIP: String { raw["tailscale_ip"] as? String ?? "" }
    var cpu: Double { num(d("cpu")["pct"]) }
    var cores: Int { Int(num(d("cpu")["count"])) }
    var load: [Double] { (d("cpu")["load"] as? [Any] ?? []).map(num) }
    var mem: Double { num(d("mem")["pct"]) }
    var memUsed: Double { num(d("mem")["used"]) }
    var memTotal: Double { num(d("mem")["total"]) }
    var disk: Double { num(d("disk")["pct"]) }
    var diskUsed: Double { num(d("disk")["used"]) }
    var diskTotal: Double { num(d("disk")["total"]) }
    var swap: Double { num(d("swap")["pct"]) }
    var netUp: Double { num(d("net")["up"]) }
    var netDown: Double { num(d("net")["down"]) }
    var netTodayRx: Double { num(d("net_today")["rx"]) }
    var netTodayTx: Double { num(d("net_today")["tx"]) }
    var uptime: Double { num(raw["uptime"]) }
    var localTime: String { [raw["localtime"] as? String, raw["tz"] as? String].compactMap { $0 }.joined(separator: " ") }
    var thermal: String { d("thermal")["state"] as? String ?? "nominal" }
    var battery: (pct: Double, plugged: Bool)? {
        let b = d("battery")
        return b.isEmpty || b["pct"] == nil ? nil : (num(b["pct"]), b["plugged"] as? Bool ?? false)
    }
    var diskETA: Double? { raw["disk_eta_days"].flatMap { $0 is NSNull ? nil : num($0) } }
    var pushedAge: Int? { raw["_age"].map { Int(num($0)) } }

    func hist(_ k: String) -> [Double] { (d("hist")[k] as? [Any] ?? []).map(num) }

    var runners: [RunnerInfo] {
        (raw["runners"] as? [[String: Any]] ?? []).map { r in
            let job = r["job"] as? [String: Any]
            return RunnerInfo(
                id: r["dir"] as? String ?? r["name"] as? String ?? UUID().uuidString,
                name: r["name"] as? String ?? "?",
                repo: r["repo"] as? String ?? "",
                status: r["status"] as? String ?? "offline",
                url: r["url"] as? String ?? "",
                jobName: job?["name"] as? String,
                branch: job?["branch"] as? String,
                elapsed: job?["elapsed"].map(num))
        }
    }

    var topApps: [AppUse] {
        (raw["top_groups"] as? [[String: Any]] ?? []).map {
            AppUse(name: $0["name"] as? String ?? "?", rss: num($0["rss"]),
                   cpu: num($0["cpu"]), procs: Int(num($0["procs"])))
        }
    }

    var worst: Double { max(cpu, mem, disk) }
}

struct Machine: Identifiable {
    let id: String          // "self" or the hub's peer key (ip:… / push:…)
    let listedName: String
    var stats: Stats?

    var name: String { stats?.host ?? listedName }
    /// "Berkay’s Mac mini" → "Mac mini": the owner prefix repeats on every tab.
    var shortName: String {
        for sep in ["’s ", "'s "] {
            if let r = name.range(of: sep) { return String(name[r.upperBound...]) }
        }
        return name
    }
    var online: Bool { stats != nil }
}

struct RunItem: Identifiable {
    let id: Int
    let repo: String
    let name: String
    let branch: String
    let status: String     // queued | in_progress
    let createdAt: Date
    let url: String
}

// MARK: - Store

@MainActor
final class Store: ObservableObject {
    @Published var machines: [Machine] = []
    @Published var unreachable: [String] = []
    @Published var runs: [RunItem]?          // nil → gh unavailable, section hidden
    @Published var hubError: String?
    @Published var lastUpdated: Date?
    let hub = Config.hub

    init(autoRefresh: Bool = true) {
        guard autoRefresh else { return }
        Task { while true { await refresh(); try? await Task.sleep(for: .seconds(5)) } }
        Task { while true { await refreshRuns(); try? await Task.sleep(for: .seconds(60)) } }
    }

    private func get(_ path: String) async -> Any? {
        guard let url = URL(string: hub.absoluteString + path) else { return nil }
        var req = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 5)
        req.httpMethod = "GET"
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? JSONSerialization.jsonObject(with: data)
    }

    func refresh() async {
        async let me = get("/api/stats")
        async let peerList = get("/api/peers")
        async let missing = get("/api/unreachable")
        guard let selfStats = await me as? [String: Any] else {
            hubError = L("Can't reach sysdash at \(hub.host ?? "?") — is it running?",
                         "\(hub.host ?? "?") adresinde sysdash'e ulaşılamıyor — çalışıyor mu?")
            lastUpdated = Date()
            return
        }
        hubError = nil
        let peers = (await peerList as? [[String: Any]] ?? []).compactMap { p -> (String, String)? in
            guard let k = p["key"] as? String else { return nil }
            return (k, p["name"] as? String ?? k)
        }
        var fetched: [String: Stats] = [:]
        await withTaskGroup(of: (String, [String: Any]?).self) { group in
            for (key, _) in peers {
                let q = key.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? key
                group.addTask { (key, await self.get("/api/peer?key=\(q)") as? [String: Any]) }
            }
            for await (key, s) in group { if let s { fetched[key] = Stats(raw: s) } }
        }
        machines = [Machine(id: "self", listedName: "", stats: Stats(raw: selfStats))]
            + peers.map { Machine(id: $0.0, listedName: $0.1, stats: fetched[$0.0]) }
        unreachable = (await missing as? [String]) ?? []
        lastUpdated = Date()
    }

    /// Repos come from the runners the fleet already reports, so nothing to configure.
    func refreshRuns() async {
        let repos = Set(machines.flatMap { $0.stats?.runners.map(\.repo) ?? [] }.filter { $0.contains("/") })
        guard let gh = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh"]
            .first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else { runs = nil; return }
        if repos.isEmpty { runs = []; return }
        let items: [RunItem]? = await Task.detached {
            var out: [RunItem] = []
            var anyOK = false
            for repo in repos {
                for status in ["queued", "in_progress"] {
                    guard let j = Shell.json(gh, ["api", "repos/\(repo)/actions/runs?status=\(status)&per_page=30"]) else { continue }
                    anyOK = true
                    for r in j["workflow_runs"] as? [[String: Any]] ?? [] {
                        out.append(RunItem(
                            id: r["id"] as? Int ?? 0, repo: repo, name: r["name"] as? String ?? "?",
                            branch: r["head_branch"] as? String ?? "", status: status,
                            createdAt: ISO8601DateFormatter().date(from: r["created_at"] as? String ?? "") ?? Date(),
                            url: r["html_url"] as? String ?? ""))
                    }
                }
            }
            return anyOK ? out.sorted { $0.createdAt < $1.createdAt } : nil   // nil: gh not logged in
        }.value
        runs = items
    }

    var allRunners: [RunnerInfo] { machines.flatMap { $0.stats?.runners ?? [] } }
    var busyCount: Int { allRunners.filter { $0.status == "busy" }.count }
    var offlineRunners: Int { allRunners.filter { $0.status == "offline" }.count }
    var queuedCount: Int { runs?.filter { $0.status == "queued" }.count ?? 0 }
    var selfStats: Stats? { machines.first?.stats }
    var alert: Bool { machines.contains { ($0.stats?.worst ?? 0) >= 95 } || hubError != nil }
}

enum Shell {
    static func json(_ path: String, _ args: [String]) -> [String: Any]? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: path)
        p.arguments = args
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        guard p.terminationStatus == 0 else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
}

// MARK: - Formatting

func bytes(_ b: Double) -> String {
    ByteCountFormatter.string(fromByteCount: Int64(b), countStyle: .memory)
}
func rate(_ b: Double) -> String { bytes(b) + "/s" }
func duration(_ s: Double) -> String {
    let s = Int(s)
    if s >= 86400 { return "\(s / 86400)\(L("d", "g")) \(s % 86400 / 3600)\(L("h", "s"))" }
    if s >= 3600 { return "\(s / 3600)\(L("h", "s")) \(s % 3600 / 60)\(L("m", "dk"))" }
    return "\(s / 60)\(L("m", "dk"))"
}
func ago(_ d: Date) -> String {
    let f = RelativeDateTimeFormatter()
    f.locale = Locale(identifier: isTR ? "tr_TR" : "en_US")
    f.unitsStyle = .short
    return f.localizedString(for: d, relativeTo: Date())
}
func level(_ pct: Double) -> Color { pct >= 95 ? .red : (pct >= 75 ? .orange : .blue) }
func open(_ s: String) { if let u = URL(string: s) { NSWorkspace.shared.open(u) } }

// MARK: - Small views

struct Dot: View {
    let color: Color
    var pulse = false
    var body: some View {
        Image(systemName: "circle.fill").font(.system(size: 7)).foregroundStyle(color)
            .symbolEffect(.pulse, isActive: pulse)
    }
}

struct Chip: View {
    let icon: String
    let text: String
    let tint: Color
    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon).font(.system(size: 10, weight: .semibold))
            Text(text).font(.system(size: 11, weight: .medium)).monospacedDigit()
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(tint.opacity(0.14), in: Capsule())
        .foregroundStyle(tint)
    }
}

struct Card<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 8) { content }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.primary.opacity(0.045)))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.primary.opacity(0.07)))
    }
}

struct SectionTitle: View {
    let text: String
    var body: some View {
        Text(text).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary).textCase(.uppercase)
    }
}

/// Thin horizontal usage bar for the overview cards.
struct MiniBar: View {
    let label: String
    let pct: Double
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(label).font(.system(size: 10)).foregroundStyle(.secondary)
                Spacer()
                Text("\(Int(pct.rounded()))%").font(.system(size: 10, weight: .semibold)).monospacedDigit()
                    .foregroundStyle(pct >= 75 ? level(pct) : .primary)
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.primary.opacity(0.08))
                    Capsule().fill(level(pct)).frame(width: g.size.width * min(max(pct, 0), 100) / 100)
                }
            }
            .frame(height: 5)
        }
    }
}

struct Sparkline: View {
    let values: [Double]
    let color: Color
    var body: some View {
        GeometryReader { g in
            Path { p in
                guard values.count > 1 else { return }
                let step = g.size.width / CGFloat(values.count - 1)
                for (i, v) in values.enumerated() {
                    let pt = CGPoint(x: CGFloat(i) * step, y: g.size.height * (1 - CGFloat(min(max(v, 0), 100)) / 100))
                    i == 0 ? p.move(to: pt) : p.addLine(to: pt)
                }
            }
            .stroke(color, style: StrokeStyle(lineWidth: 1.5, lineJoin: .round))
        }
    }
}

struct Ring: View {
    let label: String
    let pct: Double
    let sub: String
    let history: [Double]
    var body: some View {
        VStack(spacing: 5) {
            ZStack {
                Circle().stroke(Color.primary.opacity(0.08), lineWidth: 7)
                Circle().trim(from: 0, to: min(max(pct, 0), 100) / 100)
                    .stroke(level(pct), style: StrokeStyle(lineWidth: 7, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                VStack(spacing: 0) {
                    Text("\(Int(pct.rounded()))%").font(.system(size: 16, weight: .bold)).monospacedDigit()
                    Text(label).font(.system(size: 9, weight: .medium)).foregroundStyle(.secondary)
                }
            }
            .frame(width: 78, height: 78)
            Sparkline(values: Array(history.suffix(90)), color: level(pct)).frame(height: 16)
            Text(sub).font(.system(size: 10)).foregroundStyle(.secondary).monospacedDigit().lineLimit(1)
        }
        .frame(maxWidth: .infinity)
    }
}

struct RunnerRow: View {
    let r: RunnerInfo
    var body: some View {
        Button { open(r.url) } label: {
            HStack(spacing: 7) {
                Dot(color: r.status == "busy" ? .blue : (r.status == "idle" ? .green : .gray), pulse: r.status == "busy")
                VStack(alignment: .leading, spacing: 1) {
                    Text(r.name).font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(r.status == "offline" ? .secondary : .primary).lineLimit(1)
                    if r.status == "busy", let job = r.jobName {
                        Text([job, r.branch].compactMap { $0 }.joined(separator: " · "))
                            .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 4)
                if r.status == "busy" {
                    Text(r.elapsed.map(duration) ?? L("busy", "meşgul"))
                        .font(.system(size: 10, weight: .semibold)).monospacedDigit()
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(Color.blue.opacity(0.15), in: Capsule()).foregroundStyle(.blue)
                } else if r.status == "offline" {
                    Text("offline").font(.system(size: 10)).foregroundStyle(.secondary)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct RunnerGroups: View {
    let runners: [RunnerInfo]
    var body: some View {
        let byRepo = Dictionary(grouping: runners, by: { $0.repo.split(separator: "/").last.map(String.init) ?? $0.repo })
            .sorted { $0.key < $1.key }
        VStack(alignment: .leading, spacing: 6) {
            ForEach(byRepo, id: \.key) { repo, list in
                VStack(alignment: .leading, spacing: 3) {
                    SectionTitle(text: "\(repo)  \(list.filter { $0.status != "offline" }.count)/\(list.count)")
                    ForEach(list) { RunnerRow(r: $0) }
                }
            }
        }
    }
}

struct RunRow: View {
    let run: RunItem
    var body: some View {
        Button { open(run.url) } label: {
            HStack(spacing: 8) {
                Image(systemName: run.status == "queued" ? "clock" : "play.circle.fill")
                    .font(.system(size: 11)).foregroundStyle(run.status == "queued" ? .orange : .blue)
                    .frame(width: 14)
                VStack(alignment: .leading, spacing: 1) {
                    Text(run.name).font(.system(size: 12)).lineLimit(1)
                    Text("\(run.repo.split(separator: "/").last ?? "") · \(run.branch)")
                        .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Text(ago(run.createdAt)).font(.system(size: 10)).monospacedDigit().foregroundStyle(.secondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Home tab

struct MachineSummary: View {
    let m: Machine
    let select: () -> Void
    var body: some View {
        Card {
            Button(action: select) {
                HStack(spacing: 8) {
                    Image(systemName: "desktopcomputer").font(.system(size: 15))
                        .foregroundStyle(m.online ? Color.accentColor : .secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(m.name).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                        if let s = m.stats {
                            Text([m.id == "self" ? L("this Mac", "bu Mac") : nil,
                                  s.pushedAge.map { L("push · \($0)s ago", "push · \($0) sn önce") },
                                  "\(L("up", "açık")) \(duration(s.uptime))"]
                                .compactMap { $0 }.joined(separator: " · "))
                                .font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Dot(color: m.online ? .green : .red)
                    Image(systemName: "chevron.right").font(.system(size: 10)).foregroundStyle(.tertiary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if let s = m.stats {
                HStack(spacing: 10) {
                    MiniBar(label: "CPU", pct: s.cpu)
                    MiniBar(label: L("Memory", "Bellek"), pct: s.mem)
                    MiniBar(label: "Disk", pct: s.disk)
                }
                if !s.runners.isEmpty { RunnerGroups(runners: s.runners) }
            } else {
                Text(L("Not answering", "Yanıt vermiyor")).font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }
}

struct HomeTab: View {
    @ObservedObject var store: Store
    let select: (String) -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Chip(icon: "desktopcomputer",
                     text: "\(store.machines.filter(\.online).count)/\(store.machines.count + store.unreachable.count) \(L("online", "çevrimiçi"))",
                     tint: store.unreachable.isEmpty ? .green : .orange)
                if !store.allRunners.isEmpty {
                    Chip(icon: "bolt.fill", text: "\(store.busyCount) \(L("busy", "meşgul"))", tint: .blue)
                    if store.offlineRunners > 0 {
                        Chip(icon: "bolt.slash", text: "\(store.offlineRunners) offline", tint: .secondary)
                    }
                }
                if store.runs != nil {
                    Chip(icon: "clock", text: "\(store.queuedCount) \(L("queued", "kuyrukta"))",
                         tint: store.queuedCount > 0 ? .orange : .secondary)
                }
            }
            ForEach(store.machines) { m in MachineSummary(m: m) { select(m.id) } }
            if !store.unreachable.isEmpty {
                Card {
                    SectionTitle(text: L("Can't reach", "Ulaşılamıyor"))
                    Text(store.unreachable.joined(separator: ", ")).font(.system(size: 12))
                    Text(L("sysdash isn't installed there, or that Mac blocks inbound connections — set SYSDASH_PUSH_TO on it.",
                           "Orada sysdash kurulu değil ya da gelen bağlantıları engelliyor — o Mac'te SYSDASH_PUSH_TO kullanın."))
                        .font(.system(size: 10)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            if let runs = store.runs {
                Card {
                    SectionTitle(text: L("GitHub queue", "GitHub kuyruğu"))
                    if runs.isEmpty {
                        Text(L("Nothing waiting ✓", "Bekleyen iş yok ✓")).font(.system(size: 12)).foregroundStyle(.secondary)
                    } else {
                        ForEach(runs.prefix(8)) { RunRow(run: $0) }
                        if runs.count > 8 {
                            Text("+\(runs.count - 8)").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Machine tab

struct InfoRow: View {
    let icon: String
    let label: String
    let value: String
    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 10)).foregroundStyle(.secondary).frame(width: 14)
            Text(label).font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.system(size: 11, weight: .medium)).monospacedDigit().lineLimit(1)
        }
    }
}

struct MachineTab: View {
    let m: Machine
    let hub: URL
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let s = m.stats {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(s.host).font(.system(size: 14, weight: .semibold))
                        Text(["v\(s.version)", s.tailscaleIP.isEmpty ? nil : s.tailscaleIP, s.localTime]
                            .compactMap { $0 }.joined(separator: " · "))
                            .font(.system(size: 10)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    if s.thermal != "nominal" {
                        Chip(icon: "thermometer.high", text: s.thermal, tint: .red)
                    }
                }
                Card {
                    HStack(spacing: 4) {
                        Ring(label: "CPU", pct: s.cpu, sub: "\(s.cores) \(L("cores", "çekirdek"))", history: s.hist("cpu"))
                        Ring(label: L("MEMORY", "BELLEK"), pct: s.mem, sub: "\(bytes(s.memUsed)) / \(bytes(s.memTotal))", history: s.hist("mem"))
                        Ring(label: "DISK", pct: s.disk,
                             sub: s.diskETA.map { L("full in ~\(Int($0))d", "~\(Int($0)) günde dolar") } ?? bytes(s.diskTotal - s.diskUsed) + L(" free", " boş"),
                             history: s.hist("disk"))
                    }
                }
                Card {
                    if !s.load.isEmpty {
                        InfoRow(icon: "speedometer", label: L("Load", "Yük"),
                                value: s.load.map { String(format: "%.1f", $0) }.joined(separator: " · "))
                    }
                    InfoRow(icon: "memorychip", label: "Swap", value: "\(Int(s.swap.rounded()))%")
                    InfoRow(icon: "arrow.up.arrow.down", label: L("Network", "Ağ"),
                            value: "↓ \(rate(s.netDown))  ↑ \(rate(s.netUp))")
                    InfoRow(icon: "calendar", label: L("Today", "Bugün"),
                            value: "↓ \(bytes(s.netTodayRx))  ↑ \(bytes(s.netTodayTx))")
                    if let b = s.battery {
                        InfoRow(icon: b.plugged ? "battery.100.bolt" : "battery.75", label: L("Battery", "Pil"),
                                value: "\(Int(b.pct))%\(b.plugged ? L(" · plugged in", " · şarjda") : "")")
                    }
                    InfoRow(icon: "clock.arrow.circlepath", label: L("Uptime", "Açık kalma"), value: duration(s.uptime))
                }
                if !s.topApps.isEmpty {
                    Card {
                        SectionTitle(text: L("Top apps", "En çok kullananlar"))
                        ForEach(s.topApps.prefix(5)) { a in
                            HStack {
                                Text(a.name).font(.system(size: 12)).lineLimit(1)
                                if a.procs > 1 {
                                    Text("×\(a.procs)").font(.system(size: 10)).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text("\(Int(a.cpu.rounded()))%").font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary)
                                Text(bytes(a.rss)).font(.system(size: 11, weight: .medium)).monospacedDigit()
                                    .frame(width: 70, alignment: .trailing)
                            }
                        }
                    }
                }
                if !s.runners.isEmpty {
                    Card { RunnerGroups(runners: s.runners) }
                }
                HStack(spacing: 8) {
                    if !s.tailscaleIP.isEmpty && m.id != "self" {
                        Button { open("ssh://\(s.user)@\(s.tailscaleIP)") } label: { Label("SSH", systemImage: "terminal") }
                        Button { open("vnc://\(s.user)@\(s.tailscaleIP)") } label: {
                            Label(L("Screen", "Ekran"), systemImage: "display")
                        }
                    }
                    Spacer()
                    Button { open(hub.absoluteString) } label: {
                        Label(L("Open dashboard", "Paneli aç"), systemImage: "safari")
                    }
                }
                .controlSize(.small)
            } else {
                Card {
                    Text(m.name).font(.system(size: 13, weight: .semibold))
                    Text(L("This machine isn't answering the hub right now.", "Bu makine şu an hub'a yanıt vermiyor."))
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
            }
        }
    }
}

// MARK: - Shell

private struct ContentHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = max(value, nextValue()) }
}

struct TabButton: View {
    let title: String
    let selected: Bool
    let dot: Color?
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if let dot { Dot(color: dot) }
                Text(title).font(.system(size: 11, weight: selected ? .semibold : .regular)).lineLimit(1)
            }
            .padding(.horizontal, 9).padding(.vertical, 4)
            .background(selected ? Color.accentColor.opacity(0.18) : Color.primary.opacity(0.05), in: Capsule())
            .foregroundStyle(selected ? Color.accentColor : .primary)
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

/// "Open at login" as a per-user LaunchAgent rather than SMAppService:
/// SMAppService records the resolved bundle path, which for Homebrew is
/// `…/Cellar/mac-sysdash/<version>/` and vanishes on the next upgrade. The agent
/// opens the version-independent `…/opt/mac-sysdash/` path instead.
enum LoginItem {
    static let label = "io.github.berkayturanci.sysdash-bar"
    static var plist: URL {
        URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/LaunchAgents/\(label).plist")
    }

    static var stableAppPath: String {
        let path = Bundle.main.bundlePath
        guard let r = path.range(of: #"/Cellar/([^/]+)/[^/]+/"#, options: .regularExpression) else { return path }
        let name = path[r].split(separator: "/")[1]
        return path.replacingCharacters(in: r, with: "/opt/\(name)/")
    }

    static var enabled: Bool { FileManager.default.fileExists(atPath: plist.path) }

    static func set(_ on: Bool) {
        // Drop any registration an earlier build made through SMAppService.
        if SMAppService.mainApp.status == .enabled { try? SMAppService.mainApp.unregister() }
        guard on else { try? FileManager.default.removeItem(at: plist); return }
        let agent: [String: Any] = ["Label": label,
                                    "ProgramArguments": ["/usr/bin/open", stableAppPath],
                                    "RunAtLoad": true]
        try? FileManager.default.createDirectory(at: plist.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? PropertyListSerialization.data(fromPropertyList: agent, format: .xml, options: 0).write(to: plist)
    }
}

/// Window state. Deliberately not `@State`: in the macOS 27 SDK that is a macro
/// whose plugin ships with Xcode but not the Command Line Tools, so a Homebrew
/// build without Xcode fails on it.
@MainActor
final class WindowState: ObservableObject {
    @Published var tab: String
    // A ScrollView in a MenuBarExtra window has no ideal height and collapses to
    // zero under maxHeight alone, so it is sized to the measured content.
    @Published var contentHeight: CGFloat = 0
    @Published var loginItem = LoginItem.enabled

    init(tab: String = "home") { self.tab = tab }
}

struct ContentView: View {
    @ObservedObject var store: Store
    @ObservedObject var ui: WindowState

    private var tab: String {
        get { ui.tab }
        nonmutating set { ui.tab = newValue }
    }
    private var contentHeight: CGFloat {
        get { ui.contentHeight }
        nonmutating set { ui.contentHeight = newValue }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text("sysdash").font(.system(size: 15, weight: .bold))
                    Text(store.hub.host.map { $0 == "localhost" ? L("this Mac", "bu Mac") : $0 } ?? "")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                Spacer()
                Button { Task { await store.refresh(); await store.refreshRuns() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help(L("Refresh", "Yenile"))
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 5) {
                    TabButton(title: L("Overview", "Genel"), selected: tab == "home", dot: nil) { tab = "home" }
                    ForEach(store.machines) { m in
                        TabButton(title: m.shortName, selected: tab == m.id,
                                  dot: m.online ? level(m.stats?.worst ?? 0) : .gray) { tab = m.id }
                    }
                }
            }

            if let err = store.hubError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 11)).foregroundStyle(.red)
            }

            ScrollView {
                Group {
                    if tab != "home", let m = store.machines.first(where: { $0.id == tab }) {
                        MachineTab(m: m, hub: store.hub)
                    } else {
                        HomeTab(store: store) { tab = $0 }
                    }
                }
                .background(GeometryReader { g in
                    Color.clear.preference(key: ContentHeightKey.self, value: g.size.height)
                })
            }
            .frame(height: min(max(contentHeight, 1), 600))
            .onPreferenceChange(ContentHeightKey.self) { contentHeight = $0 }

            Divider()
            HStack(spacing: 12) {
                if let t = store.lastUpdated {
                    Text(t.formatted(date: .omitted, time: .standard))
                        .font(.system(size: 10)).monospacedDigit().foregroundStyle(.secondary)
                }
                Spacer()
                Toggle(L("Open at login", "Girişte aç"), isOn: Binding(
                    get: { ui.loginItem },
                    set: { on in
                        LoginItem.set(on)
                        ui.loginItem = LoginItem.enabled
                    }))
                    .toggleStyle(.checkbox)
                Button(L("Dashboard", "Panel")) { open(store.hub.absoluteString) }
                Button(L("Quit", "Çık")) { NSApp.terminate(nil) }
            }
            .buttonStyle(.borderless)
            .font(.system(size: 11))
        }
        .padding(14)
        .frame(width: 440)
    }
}

// MARK: - App

/// `SysdashBar --snapshot out.png [--dark] [--tab N]` renders the window to a
/// PNG and exits (tab 0 = overview, N = Nth machine) — for docs and debugging.
@MainActor
func renderSnapshot(to path: String, dark: Bool, tab: Int) {
    let store = Store(autoRefresh: false)
    var done = false
    Task { await store.refresh(); await store.refreshRuns(); done = true }
    let deadline = Date().addingTimeInterval(20)
    while !done && Date() < deadline { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
    _ = NSApplication.shared
    NSApp.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
    let selected = tab > 0 && tab <= store.machines.count ? store.machines[tab - 1].id : "home"
    let host = NSHostingView(rootView: ContentView(store: store, ui: WindowState(tab: selected))
        .background(Color(nsColor: .windowBackgroundColor)))
    host.appearance = NSApp.appearance
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 400),
                          styleMask: [.borderless], backing: .buffered, defer: false)
    window.contentView = host
    // Two passes: the scroll area's height comes from a preference set during layout.
    for _ in 0..<2 {
        host.frame = NSRect(origin: .zero, size: host.fittingSize)
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.4))
    }
    guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
    host.cacheDisplay(in: host.bounds, to: rep)
    try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
}

@main
struct Launcher {
    static func main() {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--snapshot"), i + 1 < args.count {
            let tab = args.firstIndex(of: "--tab").flatMap { $0 + 1 < args.count ? Int(args[$0 + 1]) : nil } ?? 0
            MainActor.assumeIsolated { renderSnapshot(to: args[i + 1], dark: args.contains("--dark"), tab: tab) }
            return
        }
        SysdashBarApp.main()
    }
}

struct SysdashBarApp: App {
    @StateObject private var store = Store()
    @StateObject private var ui = WindowState()

    var body: some Scene {
        MenuBarExtra {
            ContentView(store: store, ui: ui)
        } label: {
            HStack(spacing: 3) {
                Image(systemName: store.alert ? "exclamationmark.triangle.fill" : "gauge.with.dots.needle.33percent")
                if let s = store.selfStats {
                    Text("\(Int(s.cpu.rounded()))%"
                         + (store.busyCount > 0 ? " · \(store.busyCount)⚡" : "")
                         + (store.queuedCount > 0 ? " · \(store.queuedCount)⏳" : ""))
                        .monospacedDigit()
                }
            }
        }
        .menuBarExtraStyle(.window)
    }
}
