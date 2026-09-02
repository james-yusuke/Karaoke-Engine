# Karaoke Engine

Karaoke Engine は、**ReactのWeb UI + Python/FastAPI + Demucs** で動くローカルカラオケプロトタイプです。
ユーザーが選択したMP3/WAV/M4A等をPythonサーバーへ送り、ボーカルと伴奏（`no_vocals`）に分離し、React側で伴奏を再生しながらマイクで歌えます。

> 現在の主実装は `web/` と `server/` です。以前のJava/JavaFX版ソースは現行ブランチでは削除されており、READMEも現在のWeb + Python構成に合わせています。

## 現在できること

| 機能 | 状態 |
|---|---|
| React/Bun Web UI | ✅ |
| ローカル音源アップロード | ✅ MP3 / WAV / M4A / FLAC / OGG / AAC |
| Python API | ✅ FastAPI |
| ボーカル/伴奏分離 | ✅ Demucs `--two-stems vocals` |
| 伴奏（カラオケ）再生 | ✅ Reactのaudio player |
| 分離ボーカルの確認 | ✅ |
| ブラウザのマイク入力 | ✅ 入力レベル表示 |
| サンプル音源なしのデバッグ | ✅ Pythonで合成WAVを生成 |
| APIヘルスチェック | ✅ Demucs / FFmpeg状態を表示 |
| 歌詞同期 | ⏳ 未実装 |
| 採点/AI Coach | ⏳ Web/Python構成へ再実装予定 |

## アーキテクチャ

```text
Browser
  React / Bun (web/)
      |
      | multipart/form-data
      v
Python FastAPI (server/)
      |
      | demucs --two-stems vocals
      v
Demucs / PyTorch
  ├─ vocals.wav
  └─ no_vocals.wav  <-- Reactでカラオケ伴奏として再生
```

音源と分離結果はPythonプロセスのOS一時ディレクトリに置かれます。サーバー終了時に一時ディレクトリを削除し、Reactから `DELETE /api/jobs/{job_id}` を呼んだ場合もそのジョブを削除します。

## 必要環境

- Python 3.10+ 推奨
- FFmpeg
- Bun（React開発サーバー用）
- Demucs/PyTorchを動かせるCPU、または対応GPU

Demucs公式READMEでは `pip install -U demucs` と `--two-stems vocals` が案内されています。このプロジェクトでは同じ2-stemモードをPythonから呼び出しています。

## 1. Python APIを起動

macOS/Linux:

```bash
cd Karaoke-Engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt

# MP3/M4A等のデコードにFFmpegも用意してください
# macOS例: brew install ffmpeg

cd server
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Windows PowerShell:

```powershell
cd Karaoke-Engine
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server\requirements.txt
cd server
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

API確認:

```bash
curl http://localhost:8000/api/health
```

例:

```json
{
  "status": "ok",
  "separator": {
    "demucs": true,
    "ffmpeg": true,
    "model": "htdemucs",
    "device": "cpu"
  }
}
```

### Demucs設定

`server/.env.example` を参考に環境変数を設定できます。

```bash
export KARAOKE_DEMUCS_MODEL=htdemucs
export KARAOKE_DEMUCS_DEVICE=cpu
export KARAOKE_MAX_UPLOAD_MB=200
```

GPU環境では、PyTorch/CUDAの構成が正しく入っていれば `KARAOKE_DEMUCS_DEVICE=cuda` に変更できます。

## 2. Reactを起動

別ターミナルで:

```bash
cd Karaoke-Engine/web
cp .env.example .env
bun install
bun dev
```

ブラウザでBunが表示するURL（通常 `http://localhost:3000`）を開きます。

`web/.env`:

```env
BUN_PUBLIC_KARAOKE_API_URL=http://localhost:8000
```

## 使い方

1. Python APIを起動する
2. Reactを起動する
3. Web画面でMP3/WAV等を選択する
4. 「声と曲を分離する」を押す
5. PythonがDemucsで `vocals.wav` と `no_vocals.wav` を生成する
6. `INSTRUMENTAL` プレイヤーで伴奏を再生する
7. 「マイクを開始」で入力レベルを確認しながら歌う

ブラウザのマイク機能は `localhost` またはHTTPSのSecure Contextで使用してください。

## sample.mp3 がない状態でのデバッグ

実MP3をリポジトリに置く必要はありません。2段階で確認できます。

### A. Python単体セルフテスト

```bash
cd server
python self_test.py
```

このテストは標準ライブラリだけで短いステレオWAVを生成します。
中央定位の440Hzトーンを「仮ボーカル」、左右で異なる周波数を「仮伴奏」とし、デバッグ用位相差分で2つのWAVが正常に生成されることを検証します。

成功例:

```text
self-test: OK
engine: debug-phase-cancellation
synthetic input and both stems were generated successfully
```

### B. React → FastAPI のE2Eデバッグ

Web画面の **「サンプルなしでデバッグ」** を押してください。

```text
React
  -> POST /api/debug/synthetic
Python
  -> synthetic-mix.wav を生成
  -> debug separatorで vocals/no_vocals を生成
React
  -> 返された2つのaudio URLを再生
```

この経路はDemucsモデルのダウンロード前でも、API、CORS、一時ファイル、Reactのaudio playerが連携しているかを確認するためのものです。
**実際の楽曲分離は `/api/separate` でDemucsを使用します。**

## API

### `GET /api/health`

Pythonサーバー、Demucs、FFmpegの準備状況を返します。

### `POST /api/separate`

`multipart/form-data` の `file` に音源を入れます。処理完了後、ジョブIDとWAV取得URLを返します。

```bash
curl -F "file=@/path/to/song.mp3" http://localhost:8000/api/separate
```

レスポンス例:

```json
{
  "job_id": "...",
  "source_name": "song.mp3",
  "engine": "demucs:htdemucs:cpu",
  "instrumental_url": "/api/jobs/.../instrumental",
  "vocals_url": "/api/jobs/.../vocals"
}
```

### `GET /api/jobs/{job_id}/instrumental`

伴奏WAVを返します。

### `GET /api/jobs/{job_id}/vocals`

ボーカルWAVを返します。

### `DELETE /api/jobs/{job_id}`

ジョブの一時ファイルを削除します。

### `POST /api/debug/synthetic`

実音源なしでAPI/UI経路を確認するためのデバッグ専用エンドポイントです。

## 注意点

- 最初のDemucs実行時には学習済みモデルのダウンロードが発生する場合があります。
- CPUでも動作しますが、数分の楽曲は分離に時間がかかります。
- MP3/M4A等の処理にはFFmpegが必要です。
- アップロード上限は既定200MBです。
- 現在のAPIはローカル開発用途です。インターネット公開する場合は認証、レート制限、永続ジョブ管理、サイズ/時間制限などを追加してください。
- ユーザーが権利を持つ、または利用許諾された音源のみを使用してください。

## ディレクトリ

```text
Karaoke-Engine/
├─ server/
│  ├─ app.py              # FastAPI / REST API
│  ├─ separation.py       # Demucs + 合成音源 + デバッグ分離
│  ├─ self_test.py        # sample.mp3不要のセルフテスト
│  ├─ requirements.txt
│  └─ .env.example
├─ web/
│  ├─ src/App.tsx         # API連携、伴奏再生、マイクUI
│  ├─ src/index.css
│  ├─ .env.example
│  └─ package.json
└─ README.md
```
