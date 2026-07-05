# Open Duck Mini Runtime (fork: ijiwarunahello)

This is a fork of [apirrone/Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime).

## Git Rules

- **upstream への push は禁止。** `upstream` remote の push URL は `DISABLE` に設定済み。変更しないこと。
- PR は fork リポジトリ (`ijiwarunahello/Open_Duck_Mini_Runtime`) 内で完結させる。upstream リポジトリに PR を作成しない。
- デフォルトブランチは `v2_iji`。PR のベースは `v2_iji` を指定する。
- `gh pr create` 実行時は必ず `--repo ijiwarunahello/Open_Duck_Mini_Runtime` を付ける。

## Environment

- ターゲットデバイス: Raspberry Pi Zero 2 W (Debian 13 trixie, aarch64)
- Python: 3.12 (`.python-version` で固定)
- パッケージマネージャ: uv
- セットアップ: `uv sync`

## Dependencies

- `onnxruntime==1.18.1` は Python 3.12 までしか対応していない。Python バージョンを上げる場合は onnxruntime の互換性を確認すること。
