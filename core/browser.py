"""Criação do Chrome (undetected_chromedriver) alinhado à versão instalada no sistema."""
import os
import re
import subprocess

import undetected_chromedriver as uc


def installed_chrome_major():
    """Versão major do Chrome instalado (Windows: registro; fallback: executável). None se não achar."""
    override = os.getenv("CHROME_VERSION_MAIN")  # permite forçar via variável de ambiente / .env
    if override and override.isdigit():
        return int(override)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon") as key:
            return int(winreg.QueryValueEx(key, "version")[0].split(".")[0])
    except Exception:
        pass
    for path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(path):
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", f"(Get-Item '{path}').VersionInfo.ProductVersion"],
                    capture_output=True, text=True, timeout=15).stdout
                match = re.match(r"(\d+)\.", out.strip())
                if match:
                    return int(match.group(1))
            except Exception:
                pass
    return None


def new_chrome():
    """uc.Chrome() com o driver na mesma versão major do navegador (evita SessionNotCreatedException)."""
    return uc.Chrome(version_main=installed_chrome_major())
