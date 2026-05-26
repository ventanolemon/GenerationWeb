// Реестр компонентов-рендереров блоков.
//
// КЛЮЧЕВОЕ АРХИТЕКТУРНОЕ РЕШЕНИЕ ВСЕГО ФРОНТА.
//
// Здесь и только здесь живёт знание о всех типах блоков и о том, какой
// компонент их рендерит. Никакого switch/isinstance ни в одном из
// высокоуровневых компонентов (StaticTaskView, TableTaskView, ...).
//
// Чтобы добавить новый тип блока (например, GraphBlock), нужно:
//   1. Создать src/blocks/GraphBlock.tsx с типизированным props.
//   2. Дописать одну строку в этом файле.
//
// Это тот же принцип, что в ядре (Block.to_dict как четвёртый метод
// полиморфного рендеринга), в FastAPI (нет isinstance-сериализаторов),
// в C# (блоки = JsonElement, без BlockDto с nullable-полями).
// Полиморфизм проходит сквозной нитью через все четыре слоя.

import type { ComponentType } from "react";
import type { Block } from "../api/types";

import TextBlockView from "./TextBlock";
import FormulaBlockView from "./FormulaBlock";
import ImageBlockView from "./ImageBlock";
import CodeBlockView from "./CodeBlock";
import TableBlockView from "./TableBlock";
import FillInBlankBlockView from "./FillInBlankBlock";
import WordCorrectionBlockView from "./WordCorrectionBlock";

// Каждый рендерер принимает свой блок типизированно. Здесь приходится
// сделать ComponentType<any>, потому что TypeScript не умеет вывести
// корректный варьирующийся тип props для мапы. Это локальная цена за
// глобально-полиморфную архитектуру — затрагивает один файл, а не
// каждый компонент.
//
// На вызывающей стороне в BlockRenderer мы делаем сужение типа
// через discriminated union, так что real type safety сохраняется.
//
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const blockComponents: Record<string, ComponentType<{ block: any }>> = {
  text: TextBlockView,
  formula: FormulaBlockView,
  image: ImageBlockView,
  code: CodeBlockView,
  table: TableBlockView,
  fill_in_blank: FillInBlankBlockView,
  word_correction: WordCorrectionBlockView,
};

// Утилита для проверки, есть ли в реестре рендерер для конкретного блока.
// Используется в BlockRenderer для определения fallback-ветки.
export function hasRenderer(block: Block): boolean {
  return block.type in blockComponents;
}
