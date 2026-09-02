# Contributing to AI Karaoke

貢献ありがとうございます！このプロジェクトはまだプロトタイプ段階です。

## 開発の始め方

1. リポジトリをフォーク・クローン
2. （任意）YouTube検索機能を使う場合は `.env.example` を参考に `YOUTUBE_API_KEY` を環境変数として設定
3. `mvn javafx:run` で起動確認
4. ブランチを作成して変更
5. 動作確認の上でプルリクエストを作成

## レイヤー構成のルール

- UI (`com.aikaraoke.ui`) はServiceのみを呼び出し、Repository/SQLiteに直接アクセスしない
- Service (`com.aikaraoke.service`) がビジネスロジックを持つ
- Repository (`com.aikaraoke.repository`) がSQLite等の永続化を担当する
- `Main.java` にロジックを書かない（起動処理のみ）
- Phase 2の音声処理は `com.aikaraoke.service` 直下（VocalSeparationService等）と
  `com.aikaraoke.service.session`（KaraokeSession）に実装されています。
  `com.aikaraoke.service.phase2` の当初のインターフェース群は設計メモとして残していますが、
  実装は上記の具象クラスで行われています。

## 禁止事項

- ユーザーの録音データ・個人歌唱データ・ローカルDBファイルをコミットしないでください（`.gitignore`で除外されています）
- 著作権のある楽曲音源・歌詞データをリポジトリに追加しないでください
- 外部サーバーへユーザーデータを送信する実装を追加しないでください（YouTube検索・再生機能を除き、このアプリはローカル動作が前提です）
- APIキーなどの秘密情報をソースコードに直接書かないでください（環境変数 / `.env`（git-ignored）経由で渡してください）
- ユーザーが選択したローカル音源・分離結果をアプリ独自の保存フォルダに永続化しないでください（KaraokeSessionの責務を守ってください）

### YouTube連携について（重要）

`YouTubeSearchService` は公式の YouTube Data API v3 を使った検索・メタデータ取得と、
公式の埋め込みプレイヤーでの再生のみに用途を限定しています。以下は絶対に実装しないでください。

- YouTube動画からの音声抽出・ダウンロード
- YouTube音源のローカルファイルとしての保存
- YouTubeからの歌詞スクレイピング
- 非公式・非公開のYouTube内部APIの利用

## Issue / Pull Request

- 既存ファイルを変更する場合は、変更理由と影響範囲をPRの説明に記載してください
- 新機能はできるだけ既存のPhase構成（README参照）に沿って追加してください
