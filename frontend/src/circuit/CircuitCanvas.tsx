// Холст логической схемы: студент собирает схему, а не выписывает формулу.
//
// Почему это вообще возможно так дёшево. Ответом холста служит ТА ЖЕ
// строка, которую студент написал бы руками (`not(A) v (B ^ C)`), а
// сравнивает ядро ФУНКЦИИ, а не записи (`LogicSpec`, `boolean_text`).
// Поэтому холст не потребовал ни своего протокола, ни своей проверки:
// он только собирает ответ, который и так умеют проверять. Ровно это и
// обещал план (§7.3): «симулятор — это виджет ответа».
//
// Чего здесь нет и не планировалось: свободного размещения мышью,
// произвольной трассировки, отмены. Раскладка считается по глубине, как
// у генератора схем, и элементы встают сами. Это не упрощение «на
// потом»: перетаскивание не добавляет к ОТВЕТУ ничего — функция схемы от
// расположения не зависит.

import { useEffect, useMemo, useState } from "react";
import styles from "../styles/circuit.module.css";
import {
  GEOMETRY, GateType, Node, answer, arity, byId, canConnect, canvasSize,
  connect, disconnect, glyph, inputs, layout, newGate, output, problems,
  remove,
} from "./model";

interface Props {
  /** Имена входов схемы. Приходят полем ввода (`tokens`). */
  variables: string[];
  disabled?: boolean;
  /** Формула собранной схемы; пустая строка — схема не готова. */
  onFormula: (text: string) => void;
}

const PIN = 5;
const BUBBLE = 5;

export default function CircuitCanvas({ variables, disabled, onFormula }: Props) {
  const [nodes, setNodes] = useState<Node[]>(() => inputs(variables));
  const [source, setSource] = useState<string | null>(null);

  // Набор входов задаётся заданием: сменилось задание — холст начинается
  // заново, иначе на нём остались бы вентили от прошлой схемы.
  useEffect(() => {
    setNodes(inputs(variables));
    setSource(null);
  }, [variables.join(",")]);

  const placed = useMemo(() => layout(nodes), [nodes]);
  const size = useMemo(() => canvasSize(placed), [placed]);
  const troubles = useMemo(() => problems(nodes, variables), [nodes, variables]);
  const end = output(nodes);

  useEffect(() => {
    onFormula(troubles.length === 0 ? answer(nodes) : "");
  }, [nodes, troubles.length]);

  function add(type: GateType) {
    if (disabled) return;
    setNodes((current) => [...current, newGate(type)]);
  }

  function clickOutput(id: string) {
    if (disabled) return;
    setSource((current) => (current === id ? null : id));
  }

  function clickInput(gateId: string, slot: number) {
    if (disabled) return;
    const gate = byId(nodes, gateId);
    if (!gate) return;
    if (source && canConnect(nodes, source, gateId, slot)) {
      setNodes((current) => connect(current, source, gateId, slot));
      setSource(null);
      return;
    }
    // Клик по занятому входу без выбранного источника — снять провод.
    if (!source && gate.inputs[slot]) {
      setNodes((current) => disconnect(current, gateId, slot));
    }
  }

  const at = (id: string) => placed.find((p) => p.node.id === id);

  function pinsOf(id: string) {
    const spot = at(id);
    if (!spot) return { out: { x: 0, y: 0 }, in: [] as { x: number; y: number }[] };
    const { gateWidth, gateHeight } = GEOMETRY;
    const node = spot.node;
    const isInput = node.type === "INPUT";
    const width = isInput ? 30 : gateWidth;
    const height = isInput ? 30 : gateHeight;
    const need = arity(node.type);
    return {
      // У НЕ выходной контакт отодвинут за кружок инверсии. Иначе они
      // совпадают, контакт рисуется поверх — и кружок исчезает. По
      // ГОСТ 2.743-91 и НЕ, и ИЛИ подписаны единицей, поэтому без кружка
      // это ДВА НЕОТЛИЧИМЫХ элемента. Поймано скриншотом: на чертеже
      // стояли два одинаковых прямоугольника «1».
      out: {
        x: spot.x + width + (node.type === "NOT" ? BUBBLE * 2 + 2 : 0),
        y: spot.y + height / 2,
      },
      in: Array.from({ length: need }, (_, i) => ({
        x: spot.x,
        y: spot.y + (height * (i + 1)) / (need + 1),
      })),
    };
  }

  return (
    <div className={styles.canvas}>
      <div className={styles.palette}>
        <button type="button" onClick={() => add("AND")} disabled={disabled}>
          И&nbsp;(&amp;)
        </button>
        <button type="button" onClick={() => add("OR")} disabled={disabled}>
          ИЛИ&nbsp;(1)
        </button>
        <button type="button" onClick={() => add("NOT")} disabled={disabled}>
          НЕ
        </button>
        <button
          type="button"
          className={styles.clear}
          onClick={() => { setNodes(inputs(variables)); setSource(null); }}
          disabled={disabled}
        >
          Очистить
        </button>
      </div>

      <svg
        className={styles.board}
        width={size.width}
        height={size.height}
        viewBox={`0 0 ${size.width} ${size.height}`}
        role="img"
        aria-label="Холст логической схемы"
      >
        {/* Провода рисуются первыми — под элементами. */}
        {nodes.flatMap((node) =>
          node.inputs.map((childId, slot) => {
            if (!childId) return null;
            const from = pinsOf(childId).out;
            const to = pinsOf(node.id).in[slot];
            if (!to) return null;
            const middle = (from.x + to.x) / 2;
            return (
              <polyline
                key={`${node.id}:${slot}`}
                className={styles.wire}
                points={`${from.x},${from.y} ${middle},${from.y} ${middle},${to.y} ${to.x},${to.y}`}
              />
            );
          }),
        )}

        {placed.map(({ node, x, y }) => {
          const isInput = node.type === "INPUT";
          const width = isInput ? 30 : GEOMETRY.gateWidth;
          const height = isInput ? 30 : GEOMETRY.gateHeight;
          const pins = pinsOf(node.id);
          const isEnd = end?.id === node.id;
          return (
            <g key={node.id}>
              {isInput ? (
                <circle
                  cx={x + width / 2}
                  cy={y + height / 2}
                  r={13}
                  className={styles.input}
                />
              ) : (
                <rect
                  x={x}
                  y={y}
                  width={width}
                  height={height}
                  className={isEnd ? `${styles.gate} ${styles.gateEnd}` : styles.gate}
                />
              )}
              <text
                x={x + width / 2}
                y={y + height / 2 + 5}
                className={styles.glyph}
                textAnchor="middle"
              >
                {glyph(node)}
              </text>

              {/* Кружок инверсии у НЕ — по ГОСТ 2.743-91, как на чертеже
                  в условии: студент собирает то же, что видит. */}
              {node.type === "NOT" && (
                <circle
                  cx={x + width + BUBBLE}
                  cy={y + height / 2}
                  r={BUBBLE}
                  className={styles.bubble}
                />
              )}

              {pins.in.map((pin, slot) => (
                <circle
                  key={slot}
                  data-pin="in"
                  data-node={node.id}
                  data-slot={slot}
                  cx={pin.x}
                  cy={pin.y}
                  r={PIN}
                  className={
                    node.inputs[slot] ? styles.pinFilled : styles.pinEmpty
                  }
                  onClick={() => clickInput(node.id, slot)}
                >
                  <title>
                    {node.inputs[slot] ? "Снять провод" : "Подключить сюда"}
                  </title>
                </circle>
              ))}

              <circle
                data-pin="out"
                data-node={node.id}
                cx={pins.out.x}
                cy={pins.out.y}
                r={PIN}
                className={
                  source === node.id ? styles.pinArmed : styles.pinOut
                }
                onClick={() => clickOutput(node.id)}
              >
                <title>Взять выход</title>
              </circle>

              {!isInput && (
                <text
                  x={x + width - 4}
                  y={y - 4}
                  className={styles.remove}
                  textAnchor="end"
                  onClick={() => !disabled && setNodes((c) => remove(c, node.id))}
                >
                  ✕
                </text>
              )}
            </g>
          );
        })}
      </svg>

      <div className={styles.status}>
        {troubles.length > 0 ? (
          <span className={styles.trouble}>{troubles[0].text}</span>
        ) : (
          <span className={styles.formula}>{answer(nodes)}</span>
        )}
      </div>
      <p className={styles.help}>
        Кликните по выходу элемента, затем по свободному входу другого —
        появится провод. Повторный клик по занятому входу снимает его.
      </p>
    </div>
  );
}
