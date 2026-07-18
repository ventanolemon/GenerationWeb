import type { DistributionBucket, TimeseriesPoint } from "../api/types";
import { pct, shortDate } from "./format";

/**
 * Динамика по дням: столбец = все попытки (нейтральный трек), заливка =
 * верные ответы (акцент). Одноцветное part-to-whole кодирование магнитуды
 * (dataviz), слабая сетка, подпись последнего дня усилена.
 */
export function Timeseries({ series }: { series: TimeseriesPoint[] }) {
  const W = 640,
    H = 210,
    padL = 34,
    padR = 8,
    padT = 12,
    padB = 26;
  const n = series.length;
  const max = Math.max(...series.map((d) => d.attempts), 1);
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const bw = Math.min((plotW / n) * 0.64, 20);
  const x = (i: number) => padL + (i + 0.5) * (plotW / n);
  const yTop = (v: number) => padT + plotH * (1 - v / max);
  const gridVals = [0, Math.round(max / 2), max];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      role="img"
      aria-label="Динамика попыток и верных ответов по дням"
    >
      {gridVals.map((v) => (
        <g key={v}>
          <line x1={padL} x2={W - padR} y1={yTop(v)} y2={yTop(v)} stroke="var(--grid)" />
          <text
            x={padL - 7}
            y={yTop(v) + 3.5}
            textAnchor="end"
            fontSize={10}
            fill="var(--text-faint)"
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {v}
          </text>
        </g>
      ))}
      {series.map((d, i) => {
        const attH = (plotH * d.attempts) / max;
        const corrH = (plotH * d.correct) / max;
        const cx = x(i);
        const bx = cx - bw / 2;
        const last = i === n - 1;
        const labelDate = i % 5 === 0 || last;
        return (
          <g key={d.date}>
            <rect x={bx} y={padT + plotH - attH} width={bw} height={attH} rx={3} fill="var(--track)" />
            <rect
              x={bx}
              y={padT + plotH - corrH}
              width={bw}
              height={Math.max(corrH, 0)}
              rx={3}
              fill="var(--accent)"
              opacity={last ? 1 : 0.92}
            />
            <rect x={cx - plotW / n / 2} y={padT} width={plotW / n} height={plotH} fill="transparent">
              <title>{`${d.date}\nпопыток: ${d.attempts}\nверных: ${d.correct} (${
                d.attempts ? pct(d.correct / d.attempts) : "—"
              })`}</title>
            </rect>
            {labelDate && (
              <text x={cx} y={H - 9} textAnchor="middle" fontSize={9.5} fill="var(--text-faint)">
                {shortDate(d.date)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** Гистограмма распределения студентов по личной доле верных ответов. */
export function Histogram({ dist }: { dist: DistributionBucket[] }) {
  const W = 380,
    H = 210,
    padL = 12,
    padR = 8,
    padT = 24,
    padB = 42;
  const n = dist.length;
  const max = Math.max(...dist.map((d) => d.students), 1);
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const bw = (plotW / n) * 0.62;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      height={H}
      role="img"
      aria-label="Распределение студентов по доле верных ответов"
    >
      {dist.map((d, i) => {
        const cx = padL + (i + 0.5) * (plotW / n);
        const h = (plotH * d.students) / max;
        const top = padT + plotH - h;
        return (
          <g key={d.bucket}>
            <rect x={cx - bw / 2} y={top} width={bw} height={h} rx={4} fill="var(--accent)">
              <title>{`${d.bucket}: ${d.students} студ.`}</title>
            </rect>
            <text x={cx} y={top - 6} textAnchor="middle" fontSize={11} fontWeight={700} fill="var(--text)">
              {d.students}
            </text>
            <text x={cx} y={padT + plotH + 16} textAnchor="middle" fontSize={10} fill="var(--text-faint)">
              {d.bucket}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
