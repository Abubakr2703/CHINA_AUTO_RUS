"""Готовит APK для эксперимента с подписью: снять старую, подписать новой.

Шаги: удалить подпись v1, выровнять ``zipalign``, подписать ``apksigner``
и проверить сертификат. Нужны Android build-tools в ``PATH``.

Пример:

    python tools/prepare_experiment.py FDroid.apk \
        --keystore C:\\Android\\keys\\test.jks --alias test \
        --storepass testpass --out FDroid-otherkey.apk
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from china_auto_rus.core.signing import SigningError, strip_signatures

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise SystemExit(
            f"{tool} не найден в PATH. Установи Android build-tools "
            "(см. docs/russification.md, раздел про установку)."
        )
    return path


def _run(command: list[str]) -> None:
    print("  " + " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise SystemExit(f"Команда не выполнена: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path, help="исходный APK")
    parser.add_argument("--keystore", type=Path, required=True, help="файл .jks")
    parser.add_argument("--alias", required=True, help="alias ключа в хранилище")
    parser.add_argument("--storepass", required=True, help="пароль хранилища")
    parser.add_argument("--keypass", help="пароль ключа (по умолчанию тот же)")
    parser.add_argument("--out", type=Path, required=True, help="куда записать APK")
    parser.add_argument(
        "--force", action="store_true", help="перезаписать существующий --out"
    )
    args = parser.parse_args(argv)

    if not args.apk.is_file():
        print(f"APK не найден: {args.apk}", file=sys.stderr)
        return 1
    if not args.keystore.is_file():
        print(f"Хранилище ключей не найдено: {args.keystore}", file=sys.stderr)
        return 1
    if args.out.exists() and not args.force:
        print(f"Файл уже существует: {args.out} (добавь --force)", file=sys.stderr)
        return 1

    zipalign = _require("zipalign")
    apksigner = _require("apksigner")
    keypass = args.keypass or args.storepass

    try:
        unsigned = strip_signatures(args.apk.read_bytes())
    except (OSError, SigningError) as error:
        print(f"Подпись не снята: {error}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="apk_sign_") as directory:
        work = Path(directory)
        unsigned_path = work / "unsigned.apk"
        aligned_path = work / "aligned.apk"
        unsigned_path.write_bytes(unsigned)

        print(f"Исходный APK: {args.apk}")
        print(f"Подпись снята: {len(unsigned)} байт")
        try:
            _run([zipalign, "-p", "4", str(unsigned_path), str(aligned_path)])
            _run(
                [
                    apksigner,
                    "sign",
                    "--ks",
                    str(args.keystore),
                    "--ks-key-alias",
                    args.alias,
                    "--ks-pass",
                    f"pass:{args.storepass}",
                    "--key-pass",
                    f"pass:{keypass}",
                    "--out",
                    str(args.out),
                    str(aligned_path),
                ]
            )
        except SystemExit as error:
            print(error, file=sys.stderr)
            return 1

    print(f"Результат: {args.out} ({args.out.stat().st_size} байт)")
    print("Сертификат:")
    result = subprocess.run(
        [apksigner, "verify", "--print-certs", str(args.out)],
        capture_output=True,
        text=True,
    )
    for line in (result.stdout or result.stderr).splitlines():
        if "certificate DN" in line or "Signer" in line:
            print("  " + line.strip())
    if result.returncode != 0:
        print("Подпись не прошла проверку.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
