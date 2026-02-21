# aws-invoice-downloader

## 準備

1. .env に AWS 認証情報を設定してください。

例:

```
AWS_ACCESS_KEY_ID=YOUR_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=YOUR_SECRET_ACCESS_KEY
AWS_REGION=us-east-1
```

2. 依存関係をインストールします。

```
uv sync
```

## 実行

```
uv run --env-file .env python main.py
```

### 例

```console
$ uv run --env-file .env  python main.py
Select an invoice to download:
1. JPIN26-000000 | INVOICE | 2026-01
2. JPIN26-000000 | INVOICE | 2025-12
3. JPIN25-0000000 | INVOICE | 2025-11
Enter number (or 'q' to quit): q
```
