import random
from .matrix_generator import Matrix
from math import acos, degrees


class Point:
    def __init__(self, x=0, y=0, z=0, generate=False):
        if generate:
            self.generate()
        else:
            self.X = x
            self.Y = y
            self.Z = z

    def proportional(self, other):
        if self.X / other.X == self.Y / other.Y == self.Z / other.Z:
            return True
        else:
            return False

    def generate(self, one_line=None, inline=None):
        # one_line=(Point, Point, Bool); inline=(Line, Bool)
        self.X = random.randint(-5, 10)
        self.Y = random.randint(-5, 10)
        self.Z = random.randint(-5, 10)
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
        return self.X + other.X, self.Y + other.Y, self.Z + other.Z

    def __sub__(self, other):
        return self.X - other.X, self.Y - other.Y, self.Z - other.Z

    def __str__(self):
        return f"{self.X, self.Y, self.Z}"


class Vector:
    def __init__(self, a=None, b=None, coords=None, generate=False):
        self.X, self.Y, self.Z = 0, 0, 0
        if a and b:
            # self.A = a
            # self.B = b
            # print(b - a)
            self.X, self.Y, self.Z = b - a
        elif coords:
            self.X, self.Y, self.Z = coords
        if generate:
            self.generate()

    def get_coords(self):
        coords = (self.X, self.Y, self.Z)
        return coords

    def perpendicular(self):
        return Vector(coords=(-self.Y, self.X, 0))

    def generate(self):
        # self.A = Point(generate=True)
        # self.B = Point(generate=True)
        a = Point(generate=True)
        b = Point(generate=True)
        self.X, self.Y, self.Z = b - a

    def vector_mul(self, other):  # returns result vector abs
        x = Matrix([[self.Y, self.Z], [other.Y, other.Z]]).determinant()
        y = -Matrix([[self.X, self.Z], [other.X, other.Z]]).determinant()
        z = Matrix([[self.X, self.Y], [other.X, other.Y]]).determinant()
        res_z = Vector(coords=(x, y, z))
        return res_z

    def scalar_mul(self, other):
        res = self.X * other.X + self.Y * other.Y + self.Z * other.Z
        return res

    def mixed_mul(self, other_1, other_2):
        res = Matrix([[self.X, self.Y, self.Z],
                      [other_1.X, other_1.Y, other_1.Z],
                      [other_2.X, other_2.Y, other_2.Z]])
        return res.determinant()

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
        return (self.X ** 2 + self.Y ** 2 + self.Z ** 2) ** 0.5

    def __str__(self):
        return f"{self.X}, {self.Y}, {self.Z}"


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
        return None

    def __contains__(self, item):
        if ((item.X - self.point.X) / self.vector.X == (item.Y - self.point.Y) / self.vector.Y ==
                (item.Z - self.point.Z) / self.vector.Z):
            return True
        else:
            return False

    def union(self, other):
        A1, B1, C1 = self.vector.perpendicular().X, self.vector.perpendicular().Y, self.get_c()
        A2, B2, C2 = other.get_perpendicular().X, other.get_perpendicular().Y, other.get_c()

        x = ((((-C1) * B2) - (B1 * (-C2)))
             / ((A1 * B2) - (B1 * A2)))
        y = (((A1*(-C2)) - (A2 * (-C1)))
             / ((A1 * B2) - (B1 * A2)))
        return Point(x, y)

    def get_canon(self):
        return (f"(x {"+" if self.point.X < 0 else "-"} {abs(self.point.X)}) / {self.vector.X} = "
                f"(y {"+" if self.point.Y < 0 else "-"} {abs(self.point.Y)}) / {self.vector.Y} = "
                f"(z {"+" if self.point.Z < 0 else "-"} {abs(self.point.Z)}) / {self.vector.Z}")

    def get_param(self):
        # coefs = self.get_t_view()
        return (f"x = {self.vector.X} * t {"+" if self.point.X >= 0 else "-"} {abs(self.point.X)} \n"
                f"y = {self.vector.Y} * t {"+" if self.point.Y >= 0 else "-"} {abs(self.point.Y)} \n"
                f"z = {self.vector.Z} * t {"+" if self.point.Z >= 0 else "-"} {abs(self.point.Z)}")

    def get_perpendicular(self):
        obr = self.vector.perpendicular()
        return obr

    def get_c(self):  # free coefficient in obch equality
        obr = self.get_perpendicular()
        c = -(self.point.X * obr.X) - (self.point.Y * obr.Y) - (self.point.Z * obr.Z)
        return c

    def get_obch(self):
        obr = self.get_perpendicular()
        c = self.get_c()
        return f"({obr.X})x + ({obr.Y})y + ({obr.Z})z+({c}) = 0"

    def get_t_view(self):
        return (self.vector.X, self.point.X), (self.vector.Y, self.point.Y), (self.vector.Z, self.point.Z)

    def get_len(self, for_text=False):
        if self.A and self.B:
            dx, dy, dz = self.B - self.A
            l = (dx ** 2 + dy ** 2 + dz ** 2) ** 0.5
            if not for_text or int(l) == l:
                return l
            else:
                return f"sqrt({dx ** 2 + dy ** 2 + dz ** 2})"
        else:
            return None

    def get_center(self):
        if self.A and self.B:
            x = (self.A.X + self.B.X) / 2
            y = (self.A.Y + self.B.Y) / 2
            z = (self.A.Z + self.B.Z) / 2
            center = Point(x, y, z)
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
        z = 2 * proection.Z - point.Z
        return Point(x, y, z)

    def get_point_by_t(self, t):
        x = self.vector.X * t + self.point.X
        y = self.vector.Y * t + self.point.Y
        z = self.vector.Z * t + self.point.Z
        return Point(x, y, z)

    def __len__(self):
        return self.get_len()


class Surface:
    def __init__(self, p_1, p_2, p_3):
        v_1, v_2 = Vector(p_1, p_2), Vector(p_1, p_3)
        self.Normal = v_1.vector_mul(v_2)
        self.Point = p_1

    def get_d(self):
        d = -(self.Normal.X * self.Point.X + self.Normal.Y * self.Point.Y + self.Normal.Z * self.Point.Z)
        return d

    def get_obch(self):
        A, B, C = self.Normal.get_coords()
        return f"{A}x + ({B})y + ({C})z + ({self.get_d()}) = 0"

    def get_union_with_line(self, line: Line):
        if self.Normal.scalar_mul(line.vector) == 0:
            return None
        tt = line.get_t_view()
        cc = self.Normal.get_coords()
        free_c, t_c = 0, 0
        for i in range(len(tt)):
            free_c += tt[i][1] * cc[i]
            t_c += tt[i][0] * cc[i]
        free_c += self.get_d()
        t = -free_c / t_c
        return line.get_point_by_t(t)

    def get_proection_of_point(self, point):
        line = Line(point, vector=self.Normal)
        return self.get_union_with_line(line)

def get_exercise():
    task = """Заданные точки A1,A2,А3,А4 служат вершинами пирамиды A1A2A3А4. Найти:
        1) углы при вершине А1;
        2) площадь A1-A3-A4;
        3) объем пирамиды;
        4) площадь A2-A3-A4;
        5) уравнение плоскости A2_A3_A4;
        6) уравнение нормали из A1 к плоскости A2_A3_A4;
        7) проекцию точки A1 на грань A2A3A4
        8) длину высоты из вершины A2"""
    res = ""
    A1, A2, A3, A4 = Point(generate=True), Point(generate=True), Point(generate=True), Point(generate=True)
    task += f"\nкоординаты точек A1: {A1}, A2: {A2}, A3: {A3}, A4: {A4}\n"
    A1_A2_A3 = Surface(A1, A2, A3)
    A1_A2, A1_A3, A1_A4 = Vector(A1, A2), Vector(A1, A3), Vector(A1, A4)
    res += f"угол A2-A1-A3: {A1_A2.get_angle(A1_A3, text=True)}\n"
    res += f"угол A2-A1-A4: {A1_A2.get_angle(A1_A4, text=True)}\n"
    res += f"угол A3-A1-A4: {A1_A3.get_angle(A1_A4, text=True)}\n"
    res += f"площадь A1-A3-A4: {abs(A1_A3.vector_mul(A1_A4)) * 0.5}\n"
    res += f"объем пирамиды: {abs(A1_A2.mixed_mul(A1_A3, A1_A4)) * (1 / 6)}\n"
    A2_A3, A3_A4 = Vector(A2, A3), Vector(A3, A4)
    res += f"площадь A2-A3-A4: {abs(A2_A3.vector_mul(A3_A4)) * 0.5}\n"
    p_A2_A3_A4 = Surface(A2, A3, A4)
    res += f"плоскость A2_A3_A4: {p_A2_A3_A4.get_obch()}\n"
    A1H = Line(A1, vector=p_A2_A3_A4.Normal)
    res += f"уравнения A1H: {A1H.get_canon()}\n"
    res += f"проекция точки A1 на грань A2A3A4: {p_A2_A3_A4.get_proection_of_point(A1)}\n"
    res += f"плоскость A2_A3_A4: {p_A2_A3_A4.get_obch()}\n"
    p_A1_A3_A4 = Surface(A1, A3, A4)
    A2H = Line(A2, p_A1_A3_A4.get_proection_of_point(A2))
    res += f"длина высоты из вершины A2: {A2H.get_len()}\n"
    return task, res


if __name__ == "__main__":
    A1, A2, A3, A4 = Point(-3, -1, -2), Point(2, 1, -1), Point(-2, -2, 1), Point(0, -1, -3)
    A1_A2_A3 = Surface(A1, A2, A3)
    A1_A2, A1_A3, A1_A4 = Vector(A1, A2), Vector(A1, A3), Vector(A1, A4)

    print("угол A2-A1-A3: ", A1_A2.get_angle(A1_A3, text=True))
    print("угол A2-A1-A4: ", A1_A2.get_angle(A1_A4, text=True))
    print("угол A3-A1-A4: ", A1_A3.get_angle(A1_A4, text=True))
    print("площадь A1-A3-A4: ", abs(A1_A3.vector_mul(A1_A4)) * 0.5)
    print("объем пирамиды: ", abs(A1_A2.mixed_mul(A1_A3, A1_A4)) * (1 / 6))
    A2_A3, A3_A4 = Vector(A2, A3), Vector(A3, A4)
    print("площадь A2-A3-A4: ", abs(A2_A3.vector_mul(A3_A4)) * 0.5)
    p_A2_A3_A4 = Surface(A2, A3, A4)
    print("плоскость A2_A3_A4: ", p_A2_A3_A4.get_obch())
    A1H = Line(A1, vector=p_A2_A3_A4.Normal)
    print("уравнения A1H: ", A1H.get_canon())
    print(A1H.get_param())
    print("проекция точки A1 на грань A2A3A4: ", p_A2_A3_A4.get_proection_of_point(A1))
    p_A1_A3_A4 = Surface(A1, A3, A4)
    A2H = Line(A2, p_A1_A3_A4.get_proection_of_point(A2))
    print("длина высоты из вершины A2", A2H.get_len())

