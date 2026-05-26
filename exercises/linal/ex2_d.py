import random
# from matrix_generator import Matrix
from math import acos, degrees
import matplotlib.pyplot as plt


class Point:
    def __init__(self, x=0, y=0, generate=False):
        if generate:
            self.generate()
        else:
            self.X = x
            self.Y = y

    def proportional(self, other):
        if self.X / other.X == self.Y / other.Y:
            return True
        else:
            return False

    def generate(self, one_line=None, inline=None):
        # one_line=(Point, Point, Bool); inline=(Line, Bool)
        self.X = random.randint(-5, 10)
        self.Y = random.randint(-5, 10)
        if one_line:
            if one_line[2] == False:
                if self.proportional(one_line[0]) or self.proportional(one_line[1]):
                    self.generate()
            else:
                if not (self.proportional(one_line[0]) or self.proportional(one_line[1])):
                    self.generate()
        if inline:
            if inline[1] == False:
                if self in inline[0]:
                    self.generate()

    def __add__(self, other):
        return self.X + other.X, self.Y + other.Y

    def __sub__(self, other):
        return self.X - other.X, self.Y - other.Y

    def __str__(self):
        return f"{self.X, self.Y}"


class Vector:
    def __init__(self, a=None, b=None, coords=None, generate=False):
        if a and b:
            # self.A = a
            # self.B = b
            # print(b - a)
            self.X, self.Y = b - a
        elif coords:
            self.X, self.Y = coords
        if generate:
            self.generate()

    def perpendicular(self):
        return Vector(coords=(-self.Y, self.X))

    def generate(self):
        # self.A = Point(generate=True)
        # self.B = Point(generate=True)
        a = Point(generate=True)
        b = Point(generate=True)
        self.X, self.Y = b - a

    def vector_mul(self, other):  # returns result vector abs
        res_z = self.X * other.Y - self.Y * other.X
        return res_z

    def scalar_mul(self, other):
        res = self.X * other.X + self.Y * other.Y
        return res

    def get_angle(self, other, text=False):
        mul = self.scalar_mul(other)
        b_cos = mul / (abs(self) * abs(other))
        if text:
            if degrees(acos(b_cos)) % 1 == 1:
                return degrees(acos(b_cos))
            else:
                if (mul / (abs(self) * abs(other))) % 1 == 0:
                    return f"arccos({mul / (abs(self) * abs(other))})"
                return f"arccos({mul} / {abs(self) * abs(other)}) "
        else:
            return acos(b_cos)

    def __abs__(self):
        return (self.X ** 2 + self.Y ** 2) ** 0.5

    def __str__(self):
        return f"{self.X}, {self.Y}"


class Line:
    def __init__(self, a=None, b=None, vector=None):
        self.A, self.B = a, b
        if a and b:
            self.point = a
            self.vector = Vector(a, b)
        elif any((a, b)) and vector:
            self.vector = vector
            self.point = a if a else b

    def init_by_obch(self, A, B, C):
        vector = Vector(coords=(-B, A))

        x = 0
        y = -C / B
        if int(y) != y:
            for x_n in range(-15, 15):
                y_n = (-C - A * x_n) / B
                if int(y_n) == y_n:
                    x = x_n
                    y = y_n
                    break
        self.point = Point(x, y)
        self.vector = vector
        return self

    def __contains__(self, item):
        if (item.X - self.point.X) / self.vector.X == (item.Y - self.point.Y) / self.vector.Y:
            return True
        else:
            return False

    def union(self, other):
        '''x = (Matrix([[-self.get_c(), self.vector.Y], [-other.get_c(), other.vector.Y]]).determinant()
             / Matrix([[self.vector.X, self.vector.Y], [other.vector.X, other.vector.Y]]).determinant())
        y = (Matrix([[self.vector.X, -self.get_c()], [other.vector.X, -other.get_c()]]).determinant()
             / Matrix([[self.vector.X, self.vector.Y], [other.vector.X, other.vector.Y]]).determinant())'''
        A1, B1, C1 = self.vector.perpendicular().X, self.vector.perpendicular().Y, self.get_c()
        A2, B2, C2 = other.get_perpendicular().X, other.get_perpendicular().Y, other.get_c()

        x = ((((-C1) * B2) - (B1 * (-C2)))
             / ((A1 * B2) - (B1 * A2)))
        y = (((A1*(-C2)) - (A2 * (-C1)))
             / ((A1 * B2) - (B1 * A2)))
        return Point(x, y)

    def get_canon(self):
        return (f"(x {"+" if self.point.X < 0 else "-"} {abs(self.point.X)}) / {self.vector.X} = "
                f"(y {"+" if self.point.Y < 0 else "-"} {abs(self.point.Y)}) / {self.vector.Y}")

    def get_param(self):
        # coefs = self.get_t_view()
        return (f"x = {self.vector.X} * t {"+" if self.point.X >= 0 else "-"} {abs(self.point.X)} \n"
                f"y = {self.vector.Y} * t {"+" if self.point.Y >= 0 else "-"} {abs(self.point.Y)}")

    def get_perpendicular(self):
        obr = self.vector.perpendicular()
        return obr

    def get_c(self):  # free coefficient in obch equality
        obr = self.get_perpendicular()
        c = -(self.point.X * obr.X) - (self.point.Y * obr.Y)
        return c

    def get_obch(self):
        obr = self.get_perpendicular()
        c = self.get_c()
        return f"({obr.X})x + ({obr.Y})y + ({c}) = 0"

    def get_t_view(self):
        return (self.vector.X, self.point.X), (self.vector.Y, self.point.Y)

    def get_len(self, for_text=False):
        if self.A and self.B:
            dx, dy = self.B - self.A
            l = (dx ** 2 + dy ** 2) ** 0.5
            if not for_text or int(l) == l:
                return l
            else:
                return f"sqrt({dx ** 2 + dy ** 2})"
        else:
            return None

    def get_center(self):
        if self.A and self.B:
            x = (self.A.X + self.B.X) / 2
            y = (self.A.Y + self.B.Y) / 2
            center = Point(x, y)
            return center
        else:
            return None

    def get_proection_of_point(self, point):
        perp = self.vector.perpendicular()
        other_line = Line(a=point, vector=perp)
        result_point = self.union(other_line)
        return result_point

    def get_simmetric_point(self, point):
        proection = self.get_proection_of_point(point)
        x = 2 * proection.X - point.X
        y = 2 * proection.Y - point.Y
        return Point(x, y)

    def __repr__(self):
        return self.get_obch()


def draw(points):
    for sub_plot in points:
        sub_plot.append(sub_plot[0])
        plt.plot([p.X for p in sub_plot], [p.Y for p in sub_plot])
        plt.plot([p.X for p in sub_plot], [p.Y for p in sub_plot], 'ro')
        plt.show()
    return 0


def get_exercise():
    task = """Заданные точки A1,A2 служат вершинами треугольника A1A2A3, а стороны A1A3, A2A3 лежат на заданных уравнениях прямых (A1A3, (A2A3). Найти:
    1) вершину A3, длины сторон и все углы треугольника, площадь треугольника;
    2) каноническое, параметрические и общее уравнения прямой A1A2 и также прямых, идущих по медиане и высоте треугольника, проведенных через вершину A3;
    3) расстояние от точки A1 до прямой (A2A3);
    4) точку A1′, симметричную точке A1 относительно прямой (A2A3)."""
    res = ""
    a, b, c = Point(generate=True), Point(generate=True), Point(generate=True)
    ab, ac, bc = Line(a, b), Line(a, c), Line(b, c)
    task += f"координаты точек A: {a}, B: {b}\n"
    task += f"уравнения AB: {ab.get_obch()}, AC: {ac.get_obch()}\n"

    ab = Line(a, b)
    c = ac.union(bc)
    res += f"координаты точки С: {c}\n"
    ac, bc = Line(a, c), Line(b, c)
    res += f"длины A1A2: {ab.get_len(for_text=True)}, A1A3: {ac.get_len(for_text=True)}, A2A3: {bc.get_len(for_text=True)}\n"

    res += f"угол A2-A1-A3: {ac.vector.get_angle(ab.vector, text=True)}\n"
    res += f"угол A1-A3-A2: {ac.vector.get_angle(bc.vector, text=True)}\n"
    res += f"угол A1-A2-A3: {bc.vector.get_angle(Vector(b, a), text=True)}\n"

    res += f"площадь треугольника: {0.5 * abs(ac.vector.vector_mul(ab.vector))}\n"

    m = ab.get_center()
    cm = Line(c, m)
    h = Line(c, vector=ab.get_perpendicular())
    ah = Line(a, vector=bc.get_perpendicular())
    ah = Line(a, ah.union(bc))
    res += f"длина высоты: {ah.get_len(for_text=True)}\n"

    res += f"симметричная точка: {bc.get_simmetric_point(a)}\n"
    res += f"A1A2 уравнения: {ab.get_canon()}\n{ab.get_param()}\n{ab.get_obch()}\n"

    res += f"A3M уравнения: {cm.get_canon()}\n{cm.get_param()}\n{cm.get_obch()}\n"

    res += f"A3H уравнения: {h.get_canon()}\n{h.get_param()}\n{h.get_obch()}\n"

    res += f"расстояние от A1 до A2A3: {ah.get_len()}\n"
    res += f"A1' симметричная A1 относительно A2A3: {bc.get_simmetric_point(a)}\n"

    # draw([[a, b, c, a, bc.get_simmetric_point(a), ]])
    return task, res


if __name__ == "__main__":
    a, b, c = Point(generate=True), Point(generate=True), Point(generate=True)
    ab, ac, bc = Line(a, b), Line(a, c), Line(b, c)
    print(a, b, c)
    print(ab.get_obch(), ac.get_obch())

    ab = Line(a, b)
    c = ac.union(bc)
    print("координаты точки С:", c)
    ac, bc = Line(a, c), Line(b, c)
    print(f"длины A1A2: {ab.get_len(for_text=True)}, A1A3: {ac.get_len(for_text=True)}, A2A3: {bc.get_len(for_text=True)}")
    print("угол A2-A1-A3: ", ac.vector.get_angle(ab.vector, text=True))
    print("угол A1-A3-A2: ", ac.vector.get_angle(bc.vector, text=True))
    print("угол A1-A2-A3: ", bc.vector.get_angle(Vector(b, a), text=True))
    print("площадь треугольника: ", 0.5 * abs(ac.vector.vector_mul(ab.vector)))
    m = ab.get_center()
    cm = Line(c, m)
    h = Line(c, vector=ab.get_perpendicular())
    ah = Line(a, vector=bc.get_perpendicular())
    ah = Line(a, ah.union(bc))
    print("длина высоты: ", ah.get_len(for_text=True))
    print("симметричная точка", bc.get_simmetric_point(a))
    print(ac.vector, c)
    print("A1A2 уравнения: ", ab.get_canon())
    print(ab.get_param())
    print(ab.get_obch())
    
    print("A3M уравнения: ", cm.get_canon())
    print(cm.get_param())
    print(cm.get_obch())
    
    print("A3H уравнения: ", h.get_canon())
    print(h.get_param())
    print(h.get_obch())
    print(ah.union(bc))
    print("расстояние от A1 до A2A3", ah.get_len())
    print("A1' симметричная A1 относительно A2A3: ", bc.get_simmetric_point(a))
    draw([[a, b, c, a, bc.get_simmetric_point(a), ]])
    print("------")
    '''a, b, c = Point(generate=True), Point(generate=True), Point(generate=True)
    print("Точки: ", a, b, c)
    ac = Line(a, c)
    bc = Line(b, c)
    ab = Line(a, b)
    # c = ac.union(bc)
    print("координаты точки С:", c)
    # ac, bc = Line(a, c), Line(b, c)
    print(f"длины A1A2: {ab.get_len(for_text=True)}, A1A3: {ac.get_len(for_text=True)}, A2A3: {bc.get_len(for_text=True)}")
    print("угол A2-A1-A3: ", ac.vector.get_angle(ab.vector, text=True))
    print("угол A1-A3-A2: ", ac.vector.get_angle(bc.vector, text=True))
    print("угол A1-A2-A3: ", bc.vector.get_angle(Vector(b, a), text=True))
    print("площадь треугольника: ", 0.5 * abs(ac.vector.vector_mul(ab.vector)))
    m = ab.get_center()
    cm = Line(c, m)
    h = Line(c, vector=ab.get_perpendicular())
    ah = Line(a, vector=bc.get_perpendicular())
    ah = Line(a, ah.union(bc))
    print("длина высоты: ", ah.get_len(for_text=True))
    print("симметричная точка", bc.get_simmetric_point(a))
    print(ac.vector, c)
    print("A1A2 уравнения: ", ab.get_canon())
    print(ab.get_param())
    print(ab.get_obch())
    
    print("A3M уравнения: ", cm.get_canon())
    print(c, m)
    print(cm.get_param())
    print(cm.get_obch())
    
    print("A3H уравнения: ", h.get_canon())
    print(h.get_param())
    print(h.get_obch())
    print(ah.union(bc))
    print(ah.vector)
    print("расстояние от A1 до A2A3", ah.get_len())
'''