import random
import math
from typing import List, Tuple

# =============================
# Класс для генерации C-кода
# =============================
class CCodeGenerator:
    def __init__(self):
        self.includes = [
            "#include <stdio.h>",
            "#include <math.h>"
        ]
        self.prologue = "int main() {"
        self.epilogue = [
            "    return 0;",
            "}"
        ]
        self.body_lines: List[str] = []
        self.expected_output: List[str] = []  # то, что должно напечататься
        self.code_type = None  # "linear", "conditional", "loop"

    # --- 1. Генерация кода одного из трёх типов ---
    def generate_linear(self) -> Tuple[List[str], List[str]]:
        """Генерирует линейный код с 3+ переменными, математикой и инкрементом"""
        a = random.randint(4, 7)
        b = random.randint(2, 5)
        d_val = random.choice([2.0, 3.0, 4.0])  # для pow/sqrt

        # Симуляция выполнения
        a_after = a + 1  # a++
        a_after -= 1  # --a (префиксный)
        b_val = a_after * 2
        e_val = d_val ** 2 - math.sqrt(a_after + b_val)
        c_val = int(e_val) % 3

        lines = [
            f"    int a = {a}, b = {b}, c;",
            f"    float d = {d_val:.1f}f;",
            f"    double e;",
            f"    ",
            f"    a++;",
            f"    b = --a * 2;",
            f"    e = pow(d, 2) - sqrt(a + b);",
            f"    c = (int)e % 3;",
            f"    ",
            f"    printf(\"Values: a=%d, b=%d, c=%d\\n\", a, b, c);",
            f"    printf(\"e=%.2f\\n\", e);"
        ]
        outputs = [
            f"Values: a={a_after}, b={b_val}, c={c_val}",
            f"e={e_val:.2f}"
        ]
        return lines, outputs

    def generate_conditional(self) -> Tuple[List[str], List[str]]:
        """Генерирует условный код с 3+ переменными, математикой и инкрементом"""
        x = random.randint(6, 10)
        y = random.randint(3, 7)
        z = random.randint(1, 3)

        # Симуляция выполнения
        x_after = x - 1  # x--
        condition = (x_after * y) > (z ** 3)

        if condition:
            y_after = y + 3
            z_after = z + 1  # z++
            avg = (x_after + y_after + z_after) / 3.0
            outputs = [f"Branch A: avg={avg:.1f}"]
            branch_code = [
                f"        y += 3;",
                f"        z++;",
                f"        avg = (x + y + z) / 3.0f;",
                f"        printf(\"Branch A: avg=%.1f\\n\", avg);"
            ]
        else:
            temp = math.sin(x_after) * 10
            diff = abs(temp - y)
            z_after = z - 1  # --z
            outputs = [f"Branch B: diff={diff:.2f}, z={z_after}"]
            branch_code = [
                f"        float temp = sin(x) * 10;",
                f"        diff = fabs(temp - y);",
                f"        --z;",
                f"        printf(\"Branch B: diff=%.2f, z=%d\\n\", diff, z);"
            ]

        lines = [
                    f"    int x = {x}, y = {y}, z = {z};",
                    f"    float avg, diff;",
                    f"    ",
                    f"    x--;",
                    f"    if (x * y > pow(z, 3)) {{"
                ] + branch_code + [
                    f"    }}",
                    f"    "
                ]
        return lines, outputs

    def generate_loop(self) -> Tuple[List[str], List[str]]:
        """Генерирует циклический код с 3+ переменными, математикой и инкрементом"""
        start = 1
        end = random.randint(3, 5)
        factor_start = random.randint(1, 3)

        # Симуляция выполнения
        sum_val = 0
        factor = factor_start
        product = 1.0
        log_sum = 0.0

        for i in range(start, end + 1):
            sum_val += i * factor
            product *= math.log10(i + 1)
            log_sum += sum_val / i
            factor += 1  # factor++

        lines = [
            f"    int i, sum = 0, factor = {factor_start};",
            f"    double product = 1.0;",
            f"    float log_sum = 0.0f;",
            f"    ",
            f"    for (i = {start}; i <= {end}; i++) {{",
            f"        sum += i * factor;",
            f"        product *= log10(i + 1);",
            f"        log_sum += (float)sum / i;",
            f"        factor++;",
            f"    }}",
            f"    ",
            f"    printf(\"Loop results:\\n\");",
            f"    printf(\"sum=%d\\n\", sum);",
            f"    printf(\"product=%.3f\\n\", product);",
            f"    printf(\"log_sum=%.2f\\n\", log_sum);"
        ]
        outputs = [
            f"Loop results:",
            f"sum={sum_val}",
            f"product={product:.3f}",
            f"log_sum={log_sum:.2f}"
        ]
        return lines, outputs

    def generate_code(self):
        """Генерирует валидный C-код и сохраняет ожидаемый вывод"""
        types = {
            "linear": self.generate_linear,
            "conditional": self.generate_conditional,
            "loop": self.generate_loop
        }
        choice = random.choice(list(types.keys()))
        self.code_type = choice
        body, outputs = types[choice]()
        self.body_lines = body
        self.expected_output = outputs

    # --- 2. Получение полного кода как списка строк ---
    def get_full_code_lines(self) -> List[str]:
        return self.includes + [self.prologue] + self.body_lines + self.epilogue

    def mistake_missing_semicolon(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines)
                      if ';' in line
                      and not line.strip().startswith('#')
                      and '{' not in line and '}' not in line
                      and 'for' not in line]  # Исключаем for (i=0; i<5; i++)
        if not candidates:
            return False

        idx = random.choice(candidates)
        original_line = code_lines[idx]
        code_lines[idx] = code_lines[idx].rstrip().rstrip(';')

        # Проверяем, что строка действительно изменилась
        if code_lines[idx] == original_line:
            return False

        mistakes_log.append(f"line {idx + 1}: missing ';'")
        return True

    def mistake_wrong_brace(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines) if any(br in line for br in "{}")]
        if not candidates:
            return False

        idx = random.choice(candidates)
        line = code_lines[idx]

        if '{' in line and random.choice([True, False]):
            code_lines[idx] = line.replace('{', '}', 1)
            mistakes_log.append(f"line {idx + 1}: {{ → }}")
            return True
        elif '}' in line:
            code_lines[idx] = line.replace('}', '{', 1)
            mistakes_log.append(f"line {idx + 1}: }} → {{")
            return True

        return False

    def mistake_missing_paren(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines)
                      if '(' in line and ')' in line
                      and ('printf' in line or 'if' in line or 'for' in line or 'pow' in line)]
        if not candidates:
            return False

        idx = random.choice(candidates)
        line = code_lines[idx]
        if random.choice([True, False]) and '(' in line:
            new_basket = random.choice("[{)")
            code_lines[idx] = line.replace('(', new_basket, 1)
            mistakes_log.append(f"line {idx + 1}: ( → {new_basket}")
            return True
        elif ')' in line:
            new_basket = random.choice("]}(")
            code_lines[idx] = line.replace(')', new_basket, 1)
            mistakes_log.append(f"line {idx + 1}: ) → {new_basket}")
            return True

        return False

    def mistake_typo_printf(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines) if 'printf' in line]
        if not candidates:
            return False

        idx = random.choice(candidates)
        original = code_lines[idx]
        typo = random.choice(['prinft', 'print', 'prinf'])
        code_lines[idx] = code_lines[idx].replace('printf', typo, 1)

        if code_lines[idx] == original:
            return False

        mistakes_log.append(f"line {idx + 1}: printf → {typo}")
        return True

    def mistake_invalid_operator_sequence(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines)
                      if any(op in line for op in ['+', '-', '*', '/', '='])
                      and not line.strip().startswith('#')
                      and 'for' not in line  # Исключаем for-циклы
                      and ';' in line]
        if not candidates:
            return False

        idx = random.choice(candidates)
        line = code_lines[idx]

        # Ищем операторы для замены, исключаем замену на = = в printf, т.к. там = в кавычках
        if "pr" in line:
            replacements = [
                (' + ', ' ++ '),  # a + b → a + + b
                # (' = ', ' = = '),  # x = 5 → x = = 5
                (' * ', ' ** '),  # a * b → a * * b
                (' - ', ' -- '),  # i - 1 → i - - 1
            ]
        else:
            replacements = [
                (' + ', ' ++ '),  # a + b → a + + b
                (' = ', ' = = '),  # x = 5 → x = = 5
                (' * ', ' ** '),  # a * b → a * * b
                (' - ', ' -- '),  # i - 1 → i - - 1
            ]

        for orig, repl in replacements:
            if orig in line and repl not in line:
                code_lines[idx] = line.replace(orig, repl, 1)
                mistakes_log.append(f"line {idx + 1}: '{orig.strip()}' → '{repl.strip()}' (invalid sequence)")
                return True

        return False

    def mistake_missing_include(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines) if line.startswith('#include')]
        if not candidates:
            return False

        idx = random.choice(candidates)
        original = code_lines[idx]
        code_lines[idx] = code_lines[idx].replace('.h', '')

        if code_lines[idx] == original:
            return False

        mistakes_log.append(f"line {idx + 1}: missing '.h' in include")
        return True

    def mistake_undeclared_var(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        candidates = [i for i, line in enumerate(code_lines)
                      if any(var in line for var in [' a ', ' b ', ' c ', ' x ', ' y ', ' z ', ' i '])]
        # 'printf' in line
        # and any(v in line for v in ['%d', '%f', '%c'])
        # and
        if not candidates:
            print("------------------")
            return False

        idx = random.choice(candidates)
        line = code_lines[idx]

        # Ищем переменную для замены
        for var in [' a ', ' b ', ' c ', ' x ', ' y ', ' z ', ' i ']:
            if var in line and "pr" not in line:  # Исключаем функции f'({var}' not in line and
                fake_var = var.rstrip() + random.choice(['_tmp', '_val', '_res', '1'])
                new_line = line.replace(var, fake_var, 1)
                # # Проверяем, что замена не сломала строку полностью
                # if new_line.count('"') % 2 == 0:  # Четное число кавычек
                code_lines[idx] = new_line
                mistakes_log.append(f"line {idx + 1}: use of undeclared '{fake_var}'")
                return True
        print(line)
        return False

    def mistake_printf_format_mismatch(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        printf_candidates = [
            i for i, line in enumerate(code_lines)
            if 'printf' in line and '"' in line and ('%d' in line or '%f' in line or '%c' in line)
        ]
        if not printf_candidates:
            return False

        idx = random.choice(printf_candidates)
        line = code_lines[idx]

        # Карта несоответствий
        mismatches = {
            '%d': '%f',  # int → float
            '%i': '%f',
            '%f': '%d',  # float → int
            '%lf': '%d',
            '%c': '%s',  # char → string
            '%s': '%d',  # string → int
        }

        for correct, wrong in mismatches.items():
            if correct in line:
                new_line = line.replace(correct, wrong, 1)
                code_lines[idx] = new_line
                mistakes_log.append(f"line {idx + 1}: format '{correct}' → '{wrong}'")
                return True

        return False

    def mistake_invalid_operator_type(self, code_lines: List[str], mistakes_log: List[str]) -> bool:
        # Ищем строки с инкрементом/декрементом или битовыми операциями
        op_candidates = [
            i for i, line in enumerate(code_lines)
            if any(op in line for op in ['++', '--', '<<', '>>'])
               and not line.strip().startswith('#')
               and 'for' not in line  # Исключаем for-циклы
        ]
        if not op_candidates:
            return False

        idx = random.choice(op_candidates)
        line = code_lines[idx]

        # Ищем имя переменной
        var_name = None
        if '++' in line:
            var_name = line.split('++')[0].strip().split()[-1]
        elif '--' in line:
            var_name = line.split('--')[0].strip().split()[-1]

        # print(var_name, line, "-------------------")
        if not var_name or len(var_name) > 5:  # Защита от мусора
            # print("asas")
            return False

        # Ищем объявление переменной
        for i in range(len(code_lines)):
            if var_name in code_lines[i] and ('int ' in code_lines[i] or 'float ' in code_lines[i]):
                # Меняем тип на несовместимый
                if 'int ' in code_lines[i] and any(op in line for op in ['<<', '>>']):
                    code_lines[i] = code_lines[i].replace('int ', 'float ', 1)
                    mistakes_log.append(f"line {i + 1}: 'int {var_name}' → 'float {var_name}' (bitwise on float)")
                    return True
                elif ('float ' in code_lines[i] or 'int ' in code_lines[i]) and any(op in line for op in ['++', '--']):
                    code_lines[i] = (code_lines[i].replace('float ', 'const int ', 1)
                                     .replace('int ', 'const int ', 1))
                    mistakes_log.append(
                        f"line {i + 1}: 'float {var_name}' → 'const int {var_name}' (increment const)")
                    return True

        return False

    # --- 3. Внесение синтаксических ошибок ---

    # Функции для внесения ошибок
    def introduce_mistakes(self, count: int = 7) -> List[str]:
        code_lines = self.get_full_code_lines()
        mistakes_log = []
        all_mistake_funcs = [
            self.mistake_missing_semicolon,
            self.mistake_wrong_brace,
            self.mistake_missing_paren,
            self.mistake_typo_printf,
            self.mistake_invalid_operator_sequence,
            self.mistake_missing_include,
            self.mistake_undeclared_var,
            self.mistake_printf_format_mismatch,
            self.mistake_invalid_operator_type
        ]

        # Шаг 1: Выбираем count уникальных функций (как раньше)
        selected_funcs = random.sample(all_mistake_funcs, min(count, len(all_mistake_funcs)))
        remaining_funcs = [f for f in all_mistake_funcs if f not in selected_funcs]

        # Применяем выбранные функции
        for func in selected_funcs[:]:
            if len(mistakes_log) >= count:
                break
            if not func(code_lines, mistakes_log):
                selected_funcs.remove(func)  # Удаляем несработавшие функции

        # Шаг 2: Если ошибок меньше 7 — используем оставшиеся функции
        if len(mistakes_log) < count:
            for func in remaining_funcs[:]:
                if len(mistakes_log) >= count:
                    break
                if func(code_lines, mistakes_log):
                    remaining_funcs.remove(func)

        # Шаг 3: Если всё ещё не хватает — перебираем ВСЕ функции повторно
        attempts = 0
        max_attempts = len(all_mistake_funcs) * 3  # Защита от зацикливания
        while len(mistakes_log) < count and attempts < max_attempts:
            attempts += 1
            for func in all_mistake_funcs:
                if len(mistakes_log) >= count:
                    break
                func(code_lines, mistakes_log)  # Игнорируем результат — пытаемся любой ценой

        # Шаг 4: Критическая ситуация — принудительно добавляем ошибки
        while len(mistakes_log) < count:
            # Проще всего: удаляем ; в последних строках с операторами
            candidates = [i for i, line in enumerate(code_lines)
                          if ';' in line
                          and not line.strip().startswith('#')
                          and 'return' not in line]
            if candidates:
                idx = max(candidates)  # Берём последнюю подходящую строку
                code_lines[idx] = code_lines[idx].rstrip().rstrip(';')
                mistakes_log.append(f"line {idx + 1}: forced missing ';'")
            else:
                # Если совсем нет точек с запятой — портим include
                include_lines = [i for i, line in enumerate(code_lines) if '#include' in line]
                if include_lines:
                    idx = include_lines[0]
                    code_lines[idx] = code_lines[idx].replace('.h', '')
                    mistakes_log.append(f"line {idx + 1}: forced missing '.h'")
                else:
                    # Абсолютный крайний случай
                    code_lines[-2] = code_lines[-2].replace('return 0;', 'return error;')
                    mistakes_log.append("line -2: forced syntax error in return")

        # Обновляем внутреннее состояние
        self.includes = [line for line in code_lines if line.startswith('#include')]
        main_start = 2
        self.prologue = code_lines[main_start]
        self.body_lines = code_lines[main_start + 1: -2]
        self.epilogue = code_lines[-2:]

        return mistakes_log[:count]  # Гарантируем ровно count ошибок

    # --- 4. Получение кода как строки ---
    def __str__(self):
        return "\n".join(self.get_full_code_lines())

    # --- 5. Получить ожидаемый вывод ---
    def get_expected_output(self) -> str:
        return "\n".join(self.expected_output)


# =============================
# Пример использования
# =============================
if __name__ == "__main__":
    gen = CCodeGenerator()
    gen.generate_code()
    print(" Валидный код:")
    print(gen)
    print("\n Ожидаемый вывод:")
    print(repr(gen.get_expected_output()))
    print(f"   → {gen.get_expected_output()}")

    mistakes = gen.introduce_mistakes(7)
    print("\n Код с 7 синтаксическими ошибками:")
    print(gen)
    print("\n Внесённые ошибки:")
    for i, m in enumerate(mistakes, 1):
        print(f"{i}. {m}")