import random
from functools import reduce


class Matrix:
    def __init__(self, sp=((0, 0), (0, 0)), generate=False, size=3):
        if generate:
            sp = self.generation(size)
        self.X = len(sp[0])
        self.Y = len(sp)
        self.sp = sp

    def determinant(self):
        determinant = 0
        if self.X != self.Y:
            return "determinant is undefined"
        if self.X == 2:
            return self.sp[0][0] * self.sp[1][1] - self.sp[0][1] * self.sp[1][0]
        for i in range(self.X):
            now = self.sp[0][i] * (-1) ** i
            minor_data = [[self.sp[k][j] for j in range(self.X) if j != i] for k in range(1, self.Y)]
            minor = Matrix(minor_data)
            now *= minor.determinant()
            determinant += now
        return determinant

    def __sub__(self, other):
        for i in range(self.Y):
            for j in range(self.X):
                self.sp[i][j] += other.sp[i][j]
        return self

    def __mul__(self, other):
        if type(other) is int:
            for i in range(self.Y):
                for j in range(self.X):
                    self.sp[i][j] *= other
        elif type(other) is Matrix:
            if self.X == other.Y:
                result = [[] for _ in range(self.Y)]
                for i in range(self.Y):
                    for k in range(other.X):
                        item = 0
                        for j in range(self.X):
                            item += self.sp[i][j] * other.sp[j][k]
                        result[i].append(item)
                return Matrix(sp=result)
            else:
                return "undefined"

    def __str__(self):
        return '\n'.join([' '.join([str(i) for i in self.sp[j]]) for j in range(self.Y)])

    def generation(self, size):
        def generate_diagonal(count):
            res = []
            for _ in range(count):
                value = random.randint(-2, 3)
                res.append(value)
            return res

        def transponirovat(m):
            m = [i.copy() for i in m]
            for i in range(size):
                for j in range(i, size):
                    el = m[i][j]
                    # el = self.sp[i][j]
                    # self.sp[i][j] = self.sp[j][i]
                    # self.sp[j][i] = el
                    m[i][j] = self.sp[j][i]
                    m[j][i] = el
            return m

        def add_line(m):
            m = [i.copy() for i in m]
            # for i in range(count):
            dobovl, uvelich = random.choices([j for j in range(size)], k=2)
            coef = random.randint(-2, 2)
            for j in range(size):
                # self.sp[uvelich] += coef * self.sp[dobovl]
                for i in range(len(m[0])):
                    m[uvelich][i] += coef * m[dobovl][i]
            return m

        sp = [[0 for _ in range(size)] for _ in range(size)]
        main_daigonal = generate_diagonal(size)
        determinant = reduce(lambda a, b: a * b, main_daigonal)
        up_triangle = [main_daigonal]
        for i in range(1, size):
            new_daigonal = generate_diagonal(size - i)
            up_triangle.append(new_daigonal)

        for i in range(size):
            for j in range(size - i):
                sp[i][i + j] = up_triangle[j][i]
        # print(main_daigonal, determinant, up_triangle, sp)
        # print(*sp, sep='\n', end='\n\n')
        # print(*transponirovat(sp), sep='\n')

        things = ['transponirovat',
                  'change lines * 2',
                  'change columns * 2',
                  'add line',
                  'add column']
        operations_count = random.randint(2, 10)
        operations = []
        cnt_now = 0
        while cnt_now < operations_count:
            operation = random.choice(things)
            if operation == "transponirovat" and operations and operations[-1] != "transponirovat":
                sp = transponirovat(sp)
                print(sp)
                cnt_now += 1
            elif operation == 'add line':
                sp = add_line(sp)
                cnt_now += 1
        return sp


'''a = Matrix([[1, -1], [2, 2]])
b = Matrix([[2, -1, 0], [2, 2, 1], [1, -2, 1]])
c = Matrix([[1, -1, 0], [1, 1, 1], [1, -2, 1]])
d = Matrix([[2, -1, -2, 2], [1, 2, 2, 3], [3, 1, -1, 2], [1, 2, -2, 2]])
print(a.determinant())
print(b.determinant())
print((b * c).determinant())
print(d.determinant())
print(a * c)'''
if __name__ == "__main__":
    k = Matrix(generate=True)
    print(k)

