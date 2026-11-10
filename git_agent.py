# git_agent.py
"""
Agente de Git: detecta cambios, genera commit y push.
Uso:
    python git_agent.py "mensaje del commit"
    python git_agent.py              # mensaje automático con fecha
    python git_agent.py --status     # solo mostrar cambios
    python git_agent.py --push       # solo push (sin commit)
"""
import subprocess
import sys
from datetime import datetime


def run(cmd: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def git_status() -> str:
    _, out, _ = run(["git", "status", "--short"])
    return out


def git_diff_stat() -> str:
    _, out, _ = run(["git", "diff", "--stat"])
    return out


def git_add_all() -> bool:
    code, _, err = run(["git", "add", "."])
    if code != 0:
        print(f"❌ Error en git add: {err}")
        return False
    return True


def git_commit(message: str) -> bool:
    code, out, err = run(["git", "commit", "-m", message])
    if code == 0:
        print(f"✅ Commit creado: {message}")
        return True
    if "nothing to commit" in out or "nothing to commit" in err:
        print("ℹ️ No hay cambios para commitear.")
        return False
    print(f"❌ Error en commit: {err}")
    return False


def git_push() -> bool:
    code, out, err = run(["git", "push"])
    if code == 0:
        print("✅ Push completado.")
        return True
    print(f"❌ Error en push: {err}")
    return False


def verificar_repo() -> bool:
    code, _, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    return code == 0


def verificar_env_protegido() -> bool:
    """Verifica que .env NO esté siendo rastreado por Git."""
    code, out, _ = run(["git", "ls-files"])
    if code != 0:
        return True
    archivos = out.split("\n")
    peligrosos = [a for a in archivos if a in (".env", "setup.env")]
    if peligrosos:
        print(f"🚨 ALERTA: {peligrosos} están siendo rastreados por Git.")
        print("   Ejecuta: git rm --cached .env setup.env")
        return False
    return True


def main():
    # Verificar repo
    if not verificar_repo():
        print("❌ No estás en un repositorio Git. Ejecuta primero:")
        print("   git init -b main")
        print("   git remote add origin https://github.com/tu-usuario/tu-repo.git")
        return

    # Verificar .env protegido
    if not verificar_env_protegido():
        return

    # Modo --status
    if "--status" in sys.argv:
        status = git_status()
        if not status:
            print("ℹ️ Repositorio limpio, sin cambios.")
        else:
            print("📋 Cambios detectados:")
            print(status)
            print()
            diff = git_diff_stat()
            if diff:
                print("📊 Estadísticas:")
                print(diff)
        return

    # Modo --push
    if "--push" in sys.argv:
        git_push()
        return

    # Modo normal: commit + push
    status = git_status()
    if not status:
        print("ℹ️ No hay cambios en el repositorio.")
        return

    print("📋 Cambios detectados:")
    print(status)
    print()

    # Mensaje del commit
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        message = " ".join(args)
    else:
        message = f"Auto-commit: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # Ejecutar
    if not git_add_all():
        return
    if git_commit(message):
        git_push()


if __name__ == "__main__":
    main()
