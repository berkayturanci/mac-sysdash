# Homebrew formula for mac-sysdash (lives in this repo).
#
#   brew tap berkayturanci/mac-sysdash https://github.com/berkayturanci/mac-sysdash
#   brew install mac-sysdash
#   brew services start mac-sysdash
#
# After each GitHub release: bump `url`/`sha256` (and re-run
# `brew update-python-resources Formula/mac-sysdash.rb` if psutil changes).

class MacSysdash < Formula
  include Language::Python::Virtualenv

  desc "Tiny macOS system + GitHub Actions self-hosted runner dashboard"
  homepage "https://berkayturanci.github.io/mac-sysdash/"
  url "https://github.com/berkayturanci/mac-sysdash/archive/refs/tags/v1.34.3.tar.gz"
  sha256 "4e0ddd00bac1cf0063f5aec769266eb958b98af44cd03e3de81c12a927ee8b6c"
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

    # server.py serves static files from its own directory (HERE).
    libexec.install "server.py", "index.html", "sw.js", "manifest.webmanifest",
                    "icon.svg", "icon-180.png", "icon-192.png", "icon-512.png"

    (bin/"mac-sysdash").write <<~EOS
      #!/bin/bash
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
    environment_variables PATH: std_service_path_env, SYSDASH_PORT: "8765"
  end

  def caveats
    <<~EOS
      Start the launchd agent with:
        brew services start mac-sysdash

      Dashboard: http://localhost:8765

      Do not run ./install.sh for a brew install — that writes a separate
      launchd label (com.berkay.sysdash) and can fight brew services.

      Optional env (edit the Homebrew service plist, not a shell export):
        SYSDASH_PORT=8770
        SYSDASH_PUSH_TO=https://<hub>/api/push
    EOS
  end

  test do
    assert_match version.to_s, (libexec/"server.py").read
    assert_predicate bin/"mac-sysdash", :executable?
    system libexec/"bin/python", "-c", "import psutil"
  end
end
