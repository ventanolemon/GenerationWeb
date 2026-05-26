import type { Block } from "../api/types";
import { blockComponents, hasRenderer } from "./registry";
import styles from "../styles/blocks.module.css";

interface Props {
  block: Block;
}

/**
 * Единственная точка, через которую проходит рендер любого блока.
 * Не использует условные операторы по типам — диспатчит через мапу
 * blockComponents. Если для типа нет компонента (например, фронт
 * получил блок, добавленный в ядро после последнего деплоя фронта),
 * рендерит fallback с пометкой типа.
 */
export default function BlockRenderer({ block }: Props) {
  if (!hasRenderer(block)) {
    return (
      <div className={styles.unknownBlock}>
        <em>
          [неизвестный тип блока: {block.type}]
        </em>
      </div>
    );
  }
  const Component = blockComponents[block.type];
  return <Component block={block} />;
}

/**
 * Удобный хелпер: отрендерить массив блоков. Используется во всех
 * view-компонентах для statement/answer/feedback/prompt.
 */
export function BlockList({ blocks }: { blocks: Block[] }) {
  return (
    <div className={styles.blockList}>
      {blocks.map((block, i) => (
        <BlockRenderer key={i} block={block} />
      ))}
    </div>
  );
}
