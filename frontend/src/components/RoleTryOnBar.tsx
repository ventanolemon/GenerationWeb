// Полоса примерки роли (режим разработчика).
//
// Требование плана (§12) звучало так: примерка обязана быть ВИДИМОЙ,
// «иначе разработчик забудет и примет чужую картину за свою». Отсюда всё
// устройство этого компонента:
//
//   * полоса живёт НАД интерфейсом и не сворачивается. Раскрывающийся
//     значок в углу — это ровно то, что перестают замечать через день,
//     а замечать надо каждую минуту;
//   * она называет и примеряемую роль, и настоящую. «Вы студент» без
//     второй половины через час выглядит как «вы студент»;
//   * выход из примерки — кнопка прямо в ней. Искать, где выключается
//     режим, приходится в тот момент, когда уже запутался.
//
// Когда примерки нет, компонент показывает только вход в неё и только
// тому, кому сервер это разрешил (`canTryOn` из `GET /auth/me`).

import type { Role } from "../api/types";
import { useSession } from "../session";
import styles from "../styles/appshell.module.css";

const ROLE_RU: Record<Role, string> = {
  student: "студента",
  teacher: "преподавателя",
  admin: "администратора",
};

const OFFERED: Role[] = ["student", "teacher", "admin"];

export default function RoleTryOnBar() {
  const { canTryOn, actingRole, trueRole, tryOnRole } = useSession();

  if (!canTryOn) return null;

  if (!actingRole) {
    return (
      <div className={styles.tryOnIdle}>
        <span className={styles.tryOnLabel}>Режим разработчика:</span>
        <span>посмотреть глазами</span>
        {OFFERED.map((role) => (
          <button
            key={role}
            className={styles.tryOnPick}
            onClick={() => tryOnRole(role)}
          >
            {ROLE_RU[role]}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className={styles.tryOnBar} role="status">
      <strong>Примерка роли</strong>
      <span>
        интерфейс показан глазами {ROLE_RU[actingRole]}
        {trueRole ? `; ваша роль — ${ROLE_RU[trueRole]}` : ""}
      </span>
      <span className={styles.tryOnNote}>
        вы остаётесь собой: всё сделанное записывается на ваш логин и не
        идёт в статистику курса
      </span>
      <span className={styles.spacer} />
      {OFFERED.filter((r) => r !== actingRole).map((role) => (
        <button
          key={role}
          className={styles.tryOnPick}
          onClick={() => tryOnRole(role)}
        >
          {ROLE_RU[role]}
        </button>
      ))}
      <button className={styles.tryOnExit} onClick={() => tryOnRole(null)}>
        Выйти из примерки
      </button>
    </div>
  );
}
