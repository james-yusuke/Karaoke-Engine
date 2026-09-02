import { useCallback, useEffect, useRef, useState } from "react";
import "./index.css";

type Health = {
  status: string;
  separator: {
    demucs: boolean;
    ffmpeg: boolean;
    model: string;
    device: string;
  };
};

type SeparationResult = {
  job_id: string;
  source_name: string;
  engine: string;
  instrumental_url: string;
  vocals_url: string;
};

const API_BASE = (process.env.BUN_PUBLIC_KARAOKE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

function apiUrl(path: string) {
  return path.startsWith("http") ? path : `${API_BASE}${path}`;
}

async function readApiError(response: Response) {
  try {
    const payload = await response.json();
    return payload.detail ?? JSON.stringify(payload);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<SeparationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("音源を選択してください");
  const [error, setError] = useState("");
  const [micActive, setMicActive] = useState(false);
  const [micLevel, setMicLevel] = useState(0);

  const micStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const animationRef = useRef<number | null>(null);
  const activeJobRef = useRef<string | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/health`);
      if (!response.ok) throw new Error(await readApiError(response));
      setHealth(await response.json());
      setHealthError("");
    } catch (err) {
      setHealth(null);
      setHealthError(err instanceof Error ? err.message : "Python APIに接続できません");
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
  }, [refreshHealth]);

  const stopMic = useCallback(() => {
    if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
    animationRef.current = null;
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    micStreamRef.current = null;
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    setMicActive(false);
    setMicLevel(0);
  }, []);

  const cleanupJob = useCallback(async (jobId: string | null) => {
    if (!jobId) return;
    try {
      await fetch(`${API_BASE}/api/jobs/${jobId}`, { method: "DELETE" });
    } catch {
      // The Python process also cleans its temp directory on shutdown.
    }
  }, []);

  useEffect(() => {
    return () => {
      stopMic();
      void cleanupJob(activeJobRef.current);
    };
  }, [cleanupJob, stopMic]);

  async function acceptResult(next: SeparationResult) {
    const previous = activeJobRef.current;
    activeJobRef.current = next.job_id;
    setResult(next);
    setStatus(`分離完了 · ${next.engine}`);
    if (previous && previous !== next.job_id) await cleanupJob(previous);
  }

  async function separateSelected() {
    if (!file) return;
    setBusy(true);
    setError("");
    setStatus("Python / Demucsでボーカルと伴奏を分離しています…");

    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`${API_BASE}/api/separate`, { method: "POST", body: form });
      if (!response.ok) throw new Error(await readApiError(response));
      await acceptResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "分離に失敗しました");
      setStatus("分離に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  async function runSyntheticDebug() {
    setBusy(true);
    setError("");
    setStatus("合成音源を生成してAPI経由でデバッグしています…");
    try {
      const response = await fetch(`${API_BASE}/api/debug/synthetic`, { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      await acceptResult(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "合成音源テストに失敗しました");
      setStatus("デバッグに失敗しました");
    } finally {
      setBusy(false);
    }
  }

  async function startMic() {
    if (micActive) {
      stopMic();
      return;
    }
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
      });
      const context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);

      micStreamRef.current = stream;
      audioContextRef.current = context;
      setMicActive(true);

      const samples = new Uint8Array(analyser.fftSize);
      const update = () => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const value of samples) {
          const normalized = (value - 128) / 128;
          sum += normalized * normalized;
        }
        const rms = Math.sqrt(sum / samples.length);
        setMicLevel(Math.min(1, rms * 4));
        animationRef.current = requestAnimationFrame(update);
      };
      update();
    } catch (err) {
      setError(err instanceof Error ? `マイクを開始できません: ${err.message}` : "マイクを開始できません");
      stopMic();
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">KARAOKE ENGINE · WEB</div>
          <h1>曲から声を抜いて、そのまま歌う。</h1>
          <p className="lead">ReactからPython APIへ音源を送り、Demucsでボーカルと伴奏に分離します。</p>
        </div>
        <div className={`api-status ${health ? "online" : "offline"}`}>
          <span className="status-dot" />
          <div>
            <strong>{health ? "Python API online" : "Python API offline"}</strong>
            <small>{health ? `${health.separator.model} · ${health.separator.device}` : healthError || API_BASE}</small>
          </div>
        </div>
      </header>

      <section className="workspace">
        <div className="main-column">
          <article className="panel upload-panel">
            <div className="panel-heading">
              <div>
                <span className="step">01</span>
                <h2>音源を準備</h2>
              </div>
              <button className="ghost-button" onClick={() => void refreshHealth()}>API再確認</button>
            </div>

            <label className="dropzone">
              <input
                type="file"
                accept="audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/flac,audio/ogg,.mp3,.wav,.m4a,.flac,.ogg,.aac"
                onChange={(event: { target: { files: FileList | null } }) => setFile(event.target.files?.[0] ?? null)}
              />
              <span className="drop-icon">♫</span>
              <strong>{file ? file.name : "MP3 / WAV / M4A などを選択"}</strong>
              <small>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "ローカルファイルはPythonサーバーの一時領域だけで処理します"}</small>
            </label>

            <div className="action-row">
              <button className="primary-button" disabled={!file || busy || !health} onClick={() => void separateSelected()}>
                {busy ? "処理中…" : "声と曲を分離する"}
              </button>
              <button className="secondary-button" disabled={busy || !health} onClick={() => void runSyntheticDebug()}>
                サンプルなしでデバッグ
              </button>
            </div>
            <p className="status-line">{status}</p>
            {error && <div className="error-box">{error}</div>}
          </article>

          <article className="panel player-panel">
            <div className="panel-heading">
              <div>
                <span className="step">02</span>
                <h2>カラオケ再生</h2>
              </div>
              {result && <span className="engine-chip">{result.engine}</span>}
            </div>

            {result ? (
              <>
                <div className="now-playing">
                  <div className="cover-art">KE</div>
                  <div>
                    <span className="caption">INSTRUMENTAL</span>
                    <h3>{result.source_name}</h3>
                    <p>ボーカルを除いた伴奏です。再生してマイクで歌ってください。</p>
                  </div>
                </div>
                <audio className="audio-player" controls preload="metadata" src={apiUrl(result.instrumental_url)} />

                <details className="vocal-preview">
                  <summary>分離したボーカルを確認</summary>
                  <audio className="audio-player" controls preload="metadata" src={apiUrl(result.vocals_url)} />
                </details>
              </>
            ) : (
              <div className="empty-state">
                <span>♪</span>
                <p>分離が完了すると、ここに伴奏プレイヤーが表示されます。</p>
              </div>
            )}
          </article>
        </div>

        <aside className="side-column">
          <article className="panel mic-panel">
            <div className="panel-heading compact">
              <div>
                <span className="step">03</span>
                <h2>マイク</h2>
              </div>
            </div>
            <button className={micActive ? "danger-button" : "secondary-button full"} onClick={() => void startMic()}>
              {micActive ? "マイクを停止" : "マイクを開始"}
            </button>
            <div className="meter" aria-label="マイク入力レベル">
              <div className="meter-fill" style={{ width: `${micLevel * 100}%` }} />
            </div>
            <div className="meter-labels"><span>QUIET</span><span>{Math.round(micLevel * 100)}%</span><span>LOUD</span></div>
            <p className="hint">ヘッドホン推奨。マイク音はスピーカーへ返さず、入力レベルだけを可視化します。</p>
          </article>

          <article className="panel readiness-panel">
            <span className="caption">BACKEND READINESS</span>
            <div className="check-row"><span>Demucs</span><strong className={health?.separator.demucs ? "good" : "warn"}>{health?.separator.demucs ? "READY" : "MISSING"}</strong></div>
            <div className="check-row"><span>FFmpeg</span><strong className={health?.separator.ffmpeg ? "good" : "warn"}>{health?.separator.ffmpeg ? "READY" : "MISSING"}</strong></div>
            <div className="check-row"><span>API</span><strong className={health ? "good" : "warn"}>{health ? "READY" : "OFFLINE"}</strong></div>
            <p className="hint">実MP3分離にはDemucsとFFmpegが必要です。「サンプルなしでデバッグ」はモデルなしでもAPI/UI経路を確認できます。</p>
          </article>

          <article className="panel lyric-panel">
            <span className="caption">LYRICS</span>
            <p className="lyric-current">♪ 歌詞表示は次の実装ポイントです</p>
            <p className="lyric-next">現在は伴奏生成・再生とマイク入力までをカラオケ機能として接続しています。</p>
          </article>
        </aside>
      </section>
    </main>
  );
}

export default App;
