# Karaoke Engine Web

React/Bunフロントエンドです。音源分離はブラウザ内では行わず、`../server` のFastAPIへ送信します。

```bash
cp .env.example .env
bun install
bun dev
```

既定のAPIは `http://localhost:8000` です。変更する場合は `BUN_PUBLIC_KARAOKE_API_URL` を設定してください。

画面の「サンプルなしでデバッグ」は、Python側で合成WAVを生成するため、手元に `sample.mp3` がなくてもReact→API→音声生成→伴奏/ボーカル再生まで確認できます。
