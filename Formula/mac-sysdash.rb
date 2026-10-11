# Homebrew formula for mac-sysdash (lives in this repo).
#
#   brew tap berkayturanci/mac-sysdash https://github.com/berkayturanci/mac-sysdash
#   brew install mac-sysdash
#   brew services start mac-sysdash
#
# After each GitHub release: the formula-bump.yml workflow opens a PR to bump
# `url`/`sha256` (re-run `brew update-python-resources Formula/mac-sysdash.rb`
# if psutil changes).

class MacSysdash < Formula
  include Language::Python::Virtualenv

  desc "Mac System Dashboard: tiny macOS system + self-hosted runner dashboard"
  homepage "https://berkayturanci.github.io/mac-sysdash/"
  url "https://github.com/berkayturanci/mac-sysdash/archive/refs/tags/v1.38.1.tar.gz"
  sha256 "963ad305347ec69530af7e18ce45689ddad2d186582bc1b64759fb4eb679dc34"
  license :cannot_represent # MIT + Commons Clause — see LICENSE in the repo

  depends_on "python@3.14"
  depends_on :macos

  resource "psutil" do
    url "https://files.pythonhosted.org/packages/aa/c6/d1ddf4abb55e93cebc4f2ed8b5d6dbad109ecb8d63748dd2b20ab5e57ebe/psutil-7.2.2.tar.gz"
    sha256 "0746f5f8d406af344fd547f1c8daa5f5c33dbc293bb8d6a16d80b4bb88f59372"
  end

  def install
    venv = virtualenv_create(libexec, "python3.14")
    venv.pip_install resources

    # Menu bar companion (SwiftUI, macOS 14+). Optional: the dashboard works
    # without it. Built before libexec.install moves server.py, which build.sh
    # reads the version from.
    if MacOS.version >= :sonoma && File.exist?("menubar/build.sh")
      system "./menubar/build.sh", prefix
    end

    # server.py serves static files from its own directory (HERE).
    libexec.install "server.py", "index.html", "sw.js", "manifest.webmanifest",
                    "icon.svg", "icon-180.png", "icon-192.png", "icon-512.png"

    (bin/"mac-sysdash").write <<~EOS
      #!/bin/bash
      if [ "$1" = "menubar" ]; then
        exec open "#{opt_prefix}/Mac System Dashboard.app"
      fi
      exec "#{libexec}/bin/python" "#{libexec}/server.py" "$@"
    EOS
    chmod 0555, bin/"mac-sysdash"
  end

  service do
    run [opt_bin/"mac-sysdash"]
    keep_alive true
    working_dir opt_libexec
    log_path var/"log/mac-sysdash.log"
    error_log_path var/"log/mac-sysdash.log"
    # No SYSDASH_* here: the server reads ~/.config/mac-sysdash/config, and a
    # value pinned in the plist would override it.
    environment_variables PATH: std_service_path_env
  end

  def caveats
    <<~EOS
      Start the launchd agent with:
        brew services start mac-sysdash

      Dashboard: http://localhost:8765

      Menu bar app (macOS 14+):  mac-sysdash menubar
      Its Settings window has "Open at login" and "Show in Dock" (use that if
      a crowded menu bar hides the icon). Running the command again, or
      sysdash://open, brings up its panel.
      Before `brew uninstall`, untick "Open at login" (or delete
      ~/Library/LaunchAgents/io.github.berkayturanci.sysdash-bar.plist).

      Do not run ./install.sh for a brew install — that writes a separate
      launchd label (com.berkay.sysdash) and can fight brew services.

      Only this Mac and your tailnet can open it by default.

      Settings go in ~/.config/mac-sysdash/config (KEY=VALUE per line),
      then `brew services restart mac-sysdash`:
        SYSDASH_PORT=8770
        SYSDASH_ALLOW=lan          # also allow private LAN addresses
        SYSDASH_PUSH_TO=http://<hub-tailscale-ip>:8765/api/push
    EOS
  end

  test do
    assert_match version.to_s, (libexec/"server.py").read
    assert_predicate bin/"mac-sysdash", :executable?
    system libexec/"bin/python", "-c", "import psutil"
  end
end
