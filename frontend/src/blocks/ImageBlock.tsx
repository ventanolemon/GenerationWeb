import type { ImageBlock } from "../api/types";
import styles from "../styles/blocks.module.css";

/**
 * Картинка (например, логическая схема из ОПВС). PNG в base64.
 * Caption — подпись под изображением, может быть пустым.
 */
export default function ImageBlockView({ block }: { block: ImageBlock }) {
  if (!block.image_b64) {
    return (
      <div className={styles.imagePlaceholder}>
        [изображение недоступно: {block.caption || "без подписи"}]
      </div>
    );
  }
  return (
    <figure className={styles.imageFigure}>
      <img
        className={styles.image}
        src={`data:image/png;base64,${block.image_b64}`}
        alt={block.caption}
      />
      {block.caption && (
        <figcaption className={styles.imageCaption}>{block.caption}</figcaption>
      )}
    </figure>
  );
}
