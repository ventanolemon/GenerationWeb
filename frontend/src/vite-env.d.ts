/// <reference types="vite/client" />

// TypeScript не знает, что *.module.css при импорте — это объект
// { className: string }. Эта декларация говорит ему, как типизировать
// такие импорты. Без неё каждый import styles from "*.module.css"
// даёт "Cannot find module".
declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}
