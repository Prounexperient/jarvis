
from pathlib import Path
from shutil import copy2

from huggingface_hub import hf_hub_download

BASE = Path(__file__).resolve().parent
DESTINO = BASE / "models" / "chatterbox_ptbr"

ARQUIVOS = {
    "ve.pt": "ResembleAI/chatterbox",
    "grapheme_mtl_merged_expanded_v1.json":
        "ResembleAI/Chatterbox-Multilingual-pt-br",
}

def main():
    DESTINO.mkdir(parents=True, exist_ok=True)

    print(f"Destino: {DESTINO}")

    for nome, repositorio in ARQUIVOS.items():
        destino = DESTINO / nome

        if destino.is_file() and destino.stat().st_size > 0:
            print(f"[OK] Ja existe: {nome}")
            continue

        print(f"[DOWNLOAD] {nome}")

        origem = hf_hub_download(
            repo_id=repositorio,
            filename=nome
        )

        copy2(origem, destino)

        if not destino.is_file() or destino.stat().st_size == 0:
            raise RuntimeError(f"Falha ao preparar {nome}")

        print(f"[OK] {nome}")

    print("\nArquivos obrigatorios:")
    for nome in (
        "t3_pt_br.safetensors",
        "s3gen_v3.pt",
        "ve.pt",
        "grapheme_mtl_merged_expanded_v1.json",
    ):
        arquivo = DESTINO / nome
        status = "OK" if arquivo.is_file() and arquivo.stat().st_size > 0 else "AUSENTE"
        print(f"[{status}] {nome}")

    print("\nVerificacao concluida.")

if __name__ == "__main__":
    main()
