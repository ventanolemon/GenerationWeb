import { useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { useSession } from "../session";
import type {
  CorpusListResponse,
  CorpusRecordDetail,
  Curation,
} from "../api/types";
import { useAsync } from "../screens/useAsync";
import { num } from "../screens/format";
import s from "../styles/screens.module.css";
import k from "../styles/corpus.module.css";

const CURATION_RU: Record<Curation, string> = {
  auto: "авто",
  gold: "эталон",
  excluded: "исключено",
};
const CUR_CLASS: Record<Curation, string> = {
  auto: k.curAuto,
  gold: k.curGold,
  excluded: k.curExcluded,
};
const VERDICT_PILL: Record<string, "ok" | "warn" | "bad"> = {
  accept: "ok",
  revise: "warn",
  reject: "bad",
};

const CUR_FILTERS: { key: Curation | ""; label: string }[] = [
  { key: "", label: "Все" },
  { key: "gold", label: "Эталоны" },
  { key: "auto", label: "Не размечено" },
  { key: "excluded", label: "Исключено" },
];

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function CorpusPage() {
  const { identity } = useSession();
  const [curation, setCuration] = useState<Curation | "">("");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const { data, error, loading, reload } = useAsync<CorpusListResponse>(
    () => api.corpusList(identity!, curation ? { curation } : {}),
    [identity, curation],
  );

  const records = data?.records ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? records.filter((r) => `${r.description} ${r.id} ${r.tags.join(" ")}`.toLowerCase().includes(q)) : records;
  }, [records, search]);

  const sum = data?.summary;

  return (
    <div className={s.page}>
      <div className={s.pageHead}>
        <div>
          <h1 className={s.h1}>Корпус обучающих примеров</h1>
          <p className={s.sub}>
            curation · corpus_records · дедуп по graph_hash · разметка под дообучение (QLoRA)
          </p>
        </div>
      </div>

      {error && <div className={s.error}>Не удалось загрузить корпус: {error}</div>}
      {loading && !data && <div className={s.state}>Загрузка…</div>}

      {sum && (
        <div className={k.summaryGrid}>
          <div className={s.card}>
            <p className={s.cardTitle}>Состояние корпуса</p>
            <div className={k.stateGrid}>
              <State value={num(sum.total)} label={`записей · ${sum.generate} generate · ${sum.repair} repair`} />
              <State value={num(sum.gold)} label="золотых эталонов" cls={k.gold} />
              <State value={num(sum.auto)} label="не размечено" />
              <State value={num(sum.excluded)} label="исключено" cls={sum.excluded ? k.excluded : undefined} />
            </div>
          </div>
          <div className={s.card}>
            <p className={s.cardTitle}>Провалы по кодам таксономии</p>
            {sum.code_distribution.length === 0 ? (
              <div className={s.state} style={{ padding: 20 }}>Провалов в корпусе нет.</div>
            ) : (
              <CodeChart dist={sum.code_distribution} />
            )}
          </div>
        </div>
      )}

      <div className={s.tableCard}>
        <div className={s.tableTop}>
          <div className={s.seg} role="group" aria-label="Курация">
            {CUR_FILTERS.map((f) => (
              <button key={f.key} type="button" aria-pressed={curation === f.key} onClick={() => setCuration(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <input
            className={s.input}
            placeholder="Поиск: описание, id, тег…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ minWidth: 240 }}
          />
        </div>

        {data && filtered.length === 0 ? (
          <div className={s.state}>
            <div className={s.stateBig}>{records.length === 0 ? "Корпус пуст" : "Ничего не найдено"}</div>
            <div>{records.length === 0 ? "Записи появятся после принятых контуром заданий." : "Измените фильтр или запрос."}</div>
          </div>
        ) : (
          data && (
            <div className={s.tScroll}>
              <table className={s.t}>
                <thead>
                  <tr>
                    <th>ID / дата</th>
                    <th>Описание задачи</th>
                    <th>Коды</th>
                    <th>Валидатор</th>
                    <th>Критик</th>
                    <th className={s.num}>conf</th>
                    <th>Курация</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => setOpenId(r.id)}>
                      <td>
                        <div className={s.who}>
                          <b className={s.mono} style={{ color: "var(--text)" }}>{r.id}</b>
                          <span className={s.mono}>{fmtDate(r.created_at)}</span>
                        </div>
                      </td>
                      <td>
                        <div>{r.description}</div>
                        <div style={{ marginTop: 3 }}>{r.tags.map((t) => <span key={t} className={k.tagChip}>{t}</span>)}</div>
                      </td>
                      <td>{r.codes.length ? r.codes.map((cd) => <span key={cd} className={k.codeChip}>{cd}</span>) : <span className={s.no}>—</span>}</td>
                      <td>{r.validator_passed ? <span className={`${s.pill} ${s.ok}`}>✓ {r.seeds} seed</span> : <span className={`${s.pill} ${s.bad}`}>провал</span>}</td>
                      <td>{r.verdict ? <span className={`${s.pill} ${s[VERDICT_PILL[r.verdict] ?? "mut"]}`}>{r.verdict}</span> : <span className={s.no}>—</span>}</td>
                      <td className={s.num}>{r.confidence == null ? "—" : r.confidence.toFixed(2)}</td>
                      <td><span className={`${k.curPill} ${CUR_CLASS[r.curation]}`}>{r.curation === "gold" ? "★ " : ""}{CURATION_RU[r.curation]}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>

      {openId && (
        <RecordDrawer
          recordId={openId}
          onClose={() => setOpenId(null)}
          onCurated={() => {
            reload();
          }}
        />
      )}
    </div>
  );
}

function State({ value, label, cls }: { value: string; label: string; cls?: string }) {
  return (
    <div>
      <div className={`${k.stateVal} ${cls ?? ""}`}>{value}</div>
      <div className={k.stateLabel}>{label}</div>
    </div>
  );
}

function CodeChart({ dist }: { dist: { code: string; count: number }[] }) {
  const max = Math.max(...dist.map((d) => d.count), 1);
  return (
    <div>
      {dist.slice(0, 12).map((d) => (
        <div className={k.codeRow} key={d.code}>
          <span className={k.codeTag}>{d.code}</span>
          <span className={k.codeBarTrack}>
            <span className={k.codeBar} style={{ width: `${Math.round((d.count / max) * 100)}%` }} />
          </span>
          <span className={k.codeCount}>{d.count}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Дровер детальной записи ───────────────────────────────────────────────

function RecordDrawer({
  recordId,
  onClose,
  onCurated,
}: {
  recordId: string;
  onClose: () => void;
  onCurated: () => void;
}) {
  const { identity } = useSession();
  const { data, error, loading, reload } = useAsync<CorpusRecordDetail>(
    () => api.corpusGet(identity!, recordId),
    [identity, recordId],
  );
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [actErr, setActErr] = useState<string | null>(null);

  async function setCuration(curation: Curation) {
    setBusy(true);
    setActErr(null);
    try {
      await api.corpusSetCuration(identity!, recordId, {
        curation,
        comment: comment.trim() || (data?.comment ?? ""),
      });
      reload();
      onCurated();
    } catch (e) {
      setActErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className={k.scrim} onClick={onClose} />
      <div className={k.drawer}>
        <div className={k.drawerHead}>
          <div>
            <h3 style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: 15 }}>{recordId}</h3>
            {data && <div className={s.mono} style={{ marginTop: 3 }}>{data.kind} · {fmtDate(data.created_at)}</div>}
          </div>
          <button className={s.closeX} aria-label="Закрыть" onClick={onClose}>×</button>
        </div>
        <div className={k.drawerBody}>
          {error && <div className={s.error}>{error}</div>}
          {loading && !data && <div className={s.state}>Загрузка…</div>}
          {data && (
            <>
              <Field label="Запрос пользователя">
                <p style={{ margin: 0 }}>{data.description || "—"}</p>
              </Field>

              <Field label="Разметка">
                <span className={`${k.curPill} ${CUR_CLASS[data.curation]}`}>{data.curation === "gold" ? "★ " : ""}{CURATION_RU[data.curation]}</span>
                {data.curated_by && <span className={s.mono} style={{ marginLeft: 8 }}>{data.curated_by} · {fmtDate(data.curated_at ?? "")}</span>}
                {data.comment && <p className={s.sub} style={{ marginTop: 6 }}>«{data.comment}»</p>}
                {actErr && <div className={s.error} style={{ marginTop: 8 }}>{actErr}</div>}
                <input
                  className={s.input}
                  style={{ width: "100%", marginTop: 8 }}
                  placeholder="Комментарий куратора (необязательно)"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                />
                <div className={k.curActions}>
                  <button className={`${s.btn} ${s.sm} ${s.primary}`} disabled={busy} onClick={() => setCuration("gold")}>★ Эталон</button>
                  <button className={`${s.btn} ${s.sm} ${s.danger}`} disabled={busy} onClick={() => setCuration("excluded")}>Исключить</button>
                  <button className={`${s.btn} ${s.sm}`} disabled={busy} onClick={() => setCuration("auto")}>Сбросить</button>
                </div>
              </Field>

              <Field label="Валидатор / критик">
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  {data.validator_passed ? <span className={`${s.pill} ${s.ok}`}>✓ {data.seeds} seed</span> : <span className={`${s.pill} ${s.bad}`}>провал</span>}
                  {data.verdict && <span className={`${s.pill} ${s[VERDICT_PILL[data.verdict] ?? "mut"]}`}>{data.verdict}</span>}
                  {data.confidence != null && <span className={s.mono}>conf {data.confidence.toFixed(2)}</span>}
                  {data.human_approved && <span className={`${s.pill} ${s.ok}`}>принято человеком</span>}
                </div>
                {data.codes.length > 0 && <div style={{ marginTop: 6 }}>{data.codes.map((cd) => <span key={cd} className={k.codeChip}>{cd}</span>)}</div>}
              </Field>

              <Field label="target_graph (GraphSpec)">
                <pre className={k.jsonBlock}>{JSON.stringify((data.record as { target_graph?: unknown })?.target_graph ?? data.record, null, 2)}</pre>
              </Field>
            </>
          )}
        </div>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <p style={{ margin: "0 0 6px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-faint)" }}>{label}</p>
      {children}
    </div>
  );
}
