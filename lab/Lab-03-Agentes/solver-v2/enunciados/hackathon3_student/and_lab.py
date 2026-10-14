"""Infraestructura proporcionada para el Hackathon 3.

Motor escalar educativo escrito para este paquete. No requiere PyTorch ni GPU.
Las operaciones sigmoide y BCE son nodos proporcionados, no tareas de derivación.
No editar este archivo durante la actividad.
"""
from __future__ import annotations

import csv
import html
import math
from pathlib import Path


DATOS_AND = ((0.0, 0.0, 0), (0.0, 1.0, 0), (1.0, 0.0, 0), (1.0, 1.0, 1))
NOMBRES = ("w1", "w2", "b")
TASA = 0.5
ITERACIONES = 600


class ActividadPendiente(Exception):
    """Señala un espacio aún no completado; no es un fallo del motor."""


class Value:
    """Número escalar con valor, gradiente y padres del grafo.

    backward recorre una vez el grafo de esta ejecución. Usa += para reunir
    contribuciones. Las hojas compartidas conservan .grad hasta reiniciarlo.
    Debe construirse un forward nuevo para cada nueva iteración.
    """

    def __init__(self, data, parents=(), op="hoja", label=""):
        self.data = float(data)
        self.grad = 0.0
        self.parents = tuple(parents)
        self.op = op
        self.label = label
        self._backward = lambda: None
        self._used = False

    def __repr__(self):
        return f"Value({self.label or self.op}, valor={self.data:.6f}, grad={self.grad:.6f})"

    @staticmethod
    def wrap(value):
        return value if isinstance(value, Value) else Value(value, label=str(value))

    def __add__(self, other):
        other = self.wrap(other)
        out = Value(self.data + other.data, (self, other), "+")

        def backward():
            self.grad += out.grad
            other.grad += out.grad

        out._backward = backward
        return out

    __radd__ = __add__

    def __mul__(self, other):
        other = self.wrap(other)
        left, right = self.data, other.data
        out = Value(left * right, (self, other), "×")

        def backward():
            self.grad += right * out.grad
            other.grad += left * out.grad

        out._backward = backward
        return out

    __rmul__ = __mul__

    def topological(self):
        order, seen = [], set()

        def visit(node):
            if node in seen:
                return
            seen.add(node)
            for parent in node.parents:
                visit(parent)
            order.append(node)

        visit(self)
        return order

    def backward(self):
        if self._used:
            raise RuntimeError("Este grafo ya se recorrió. Construye un forward nuevo antes de otro backward.")
        self._used = True
        self.grad = 1.0
        for node in reversed(self.topological()):
            node._backward()


def sigmoide(z):
    """Transformación proporcionada; implementación estable de la sigmoide."""
    z = Value.wrap(z)
    p = 1.0 / (1.0 + math.exp(-z.data)) if z.data >= 0 else math.exp(z.data) / (1.0 + math.exp(z.data))
    out = Value(p, (z,), "sigmoide", "probabilidad")
    out._backward = lambda: _sumar_gradiente(z, p * (1.0 - p) * out.grad)
    return out


def _sumar_gradiente(node, contribution):
    node.grad += contribution


def perdida_binaria(p, y):
    """BCE proporcionada: menor cuando la probabilidad favorece el objetivo.

    Es un único nodo con regla local ya implementada. El objetivo y es un
    número fijo. No se recorta p: si se satura, se informa el problema.
    """
    if y not in (0, 1):
        raise ValueError("El objetivo debe ser 0 o 1.")
    if not 0.0 < p.data < 1.0:
        raise ValueError("Probabilidad saturada. Usa la tasa y las iteraciones indicadas.")
    loss = -math.log(p.data) if y else -math.log1p(-p.data)
    out = Value(loss, (p,), f"BCE con y={y}", "pérdida")
    local = -1.0 / p.data if y else 1.0 / (1.0 - p.data)
    out._backward = lambda: _sumar_gradiente(p, local * out.grad)
    return out


def crear_parametros(w1=0.0, w2=0.0, b=0.0):
    return tuple(Value(v, label=n) for n, v in zip(NOMBRES, (w1, w2, b)))


def valores(parametros):
    return tuple(p.data for p in parametros)


def gradientes(parametros):
    return tuple(p.grad for p in parametros)


def reiniciar_gradientes(parametros):
    for p in parametros:
        p.grad = 0.0


def forward_resuelto(x1, x2, parametros):
    """Ejemplo resuelto que sirve de apoyo; la práctica escribe su propia función."""
    w1, w2, b = parametros
    a = w1 * Value(x1, label="x1")
    a.label = "w1 × x1"
    c = w2 * Value(x2, label="x2")
    c.label = "w2 × x2"
    suma = a + c
    suma.label = "suma ponderada"
    z = suma + b
    z.label = "z"
    return sigmoide(z)


def tabla(filas, titulo=""):
    """Tabla HTML local sin Pandas; también queda registrada en la salida del notebook."""
    from IPython.display import HTML, display

    if not filas:
        print("Sin filas para mostrar.")
        return
    columns = list(filas[0])

    def fmt(value):
        return f"{value:.6f}" if isinstance(value, float) else str(value)

    head = "".join(f"<th scope='col'>{html.escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(fmt(row[c]))}</td>" for c in columns) + "</tr>" for row in filas)
    caption = f"<caption style='text-align:left;font-weight:bold;padding:8px 0'>{html.escape(titulo)}</caption>"
    display(HTML(f"<table style='border-collapse:collapse;font-size:14px'>{caption}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"))


def tabla_parametros(parametros, titulo="Parámetros y gradientes"):
    tabla([{"parámetro": n, "valor": p.data, "gradiente": p.grad} for n, p in zip(NOMBRES, parametros)], titulo)


def inspeccionar_grafo(loss):
    """Expone todos los nodos y conexiones de la ejecución seleccionada."""
    nodes = loss.topological()
    ids = {node: i for i, node in enumerate(nodes)}
    filas = [{"nodo": ids[n], "nombre": n.label or n.op, "operación": n.op,
              "valor": n.data, "gradiente": n.grad,
              "recibe de": ", ".join(str(ids[p]) for p in n.parents) or "sin padres"} for n in nodes]
    tabla(filas, "Grafo de esta ejecución en orden forward; backward lo recorre al revés")
    return filas


def dibujar_grafo(loss):
    """Dibujo SVG del grafo de un ejemplo; sin Graphviz ni servicios externos."""
    from IPython.display import SVG, display

    nodes = loss.topological()
    levels, groups = {}, {}
    for node in nodes:
        depth = 0 if not node.parents else 1 + max(levels[p] for p in node.parents)
        levels[node] = depth
        groups.setdefault(depth, []).append(node)
    width = 920
    height = 36 + len(groups) * 110
    positions = {}
    for depth, group in groups.items():
        for i, node in enumerate(group):
            positions[node] = ((i + 0.5) * width / len(group), 22 + depth * 110)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img"><title>Grafo de un ejemplo con valores y gradientes</title><defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#64748b"/></marker></defs><rect width="100%" height="100%" fill="white"/>']
    for node in nodes:
        x, y = positions[node]
        for parent in node.parents:
            px, py = positions[parent]
            if levels[node] - levels[parent] > 1:
                # La conexión del sesgo evita cruzar nodos de niveles intermedios.
                route = f"M{px},{py+76} L{px},{py+88} L{width-8},{py+88} L{width-8},{y+38} L{x+90},{y+38}"
            else:
                route = f"M{px},{py+76} L{x},{y-5}"
            parts.append(f'<path d="{route}" stroke="#64748b" fill="none" marker-end="url(#arrow)"/>')
    for node in nodes:
        x, y = positions[node]
        fill = "#eef2ff" if node.label in NOMBRES else "#f8fafc"
        parts.append(f'<rect x="{x-85}" y="{y}" width="170" height="76" rx="7" fill="{fill}" stroke="#64748b"/>')
        for dy, label in ((21, node.label or node.op), (43, f"valor {node.data:.4f}"), (63, f"grad {node.grad:.4f}")):
            parts.append(f'<text x="{x}" y="{y+dy}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#0f172a">{html.escape(label)}</text>')
    parts.append("</svg>")
    display(SVG("".join(parts)))


def perdida_lote(predecir, parametros):
    """Media de cuatro pérdidas, con los mismos tres objetos parámetro."""
    losses = [perdida_binaria(predecir(x1, x2, parametros), y) for x1, x2, y in DATOS_AND]
    result = (losses[0] + losses[1] + losses[2] + losses[3]) * 0.25
    result.label = "L media de 4 ejemplos"
    return result


def evaluar(predecir, parametros):
    """Forward nuevo sin backward ni actualización; las .grad se conservan."""
    filas = []
    for x1, x2, y in DATOS_AND:
        prob = predecir(x1, x2, parametros).data
        clase = int(prob >= 0.5)
        filas.append({"x1": int(x1), "x2": int(x2), "objetivo": y,
                      "probabilidad": prob, "clase": clase, "correcta": clase == y})
    return filas


def comprobar_forward(predecir, anunciar=True):
    try:
        ps = crear_parametros(0.4, -0.3, 0.2)
        before = valores(ps)
        for x1, x2 in ((0, 0), (1, 0), (0, 1), (1, 1), (0.2, -0.7)):
            p = predecir(x1, x2, ps)
            assert isinstance(p, Value), "La predicción debe ser Value, no un float ni una clase 0/1."
            expected = 1 / (1 + math.exp(-(0.4*x1 - 0.3*x2 + 0.2)))
            assert math.isclose(p.data, expected, abs_tol=1e-12), "Revisa productos, suma del sesgo y sigmoide."
            reiniciar_gradientes(ps)
            p.backward()
            for got, want in zip(gradientes(ps), (expected*(1-expected)*x1, expected*(1-expected)*x2, expected*(1-expected))):
                assert math.isclose(got, want, abs_tol=1e-12), "El forward perdió las conexiones con los parámetros. No uses .data para construir z."
        assert valores(ps) == before, "El forward no debe actualizar parámetros."
    except ActividadPendiente as exc:
        if anunciar:
            print("PENDIENTE:", exc)
        return False
    if anunciar:
        print("FORWARD CORRECTO: valores y conexiones comprobados.")
    return True


def comprobar_actualizacion(actualizar, anunciar=True):
    try:
        ps = crear_parametros(0.4, -0.2, 0.3)
        for p, g in zip(ps, (-0.6, 0.2, 0.0)):
            p.grad = g
        original_ids = tuple(map(id, ps))
        actualizar(ps, 0.1)
        for got, want in zip(valores(ps), (0.46, -0.22, 0.3)):
            assert math.isclose(got, want, abs_tol=1e-12), "Revisa valor actual - tasa × gradiente."
        assert tuple(map(id, ps)) == original_ids, "Actualiza .data; no sustituyas los objetos parámetro."
        assert gradientes(ps) == (-0.6, 0.2, 0.0), "La actualización no debe reiniciar .grad."
    except ActividadPendiente as exc:
        if anunciar:
            print("PENDIENTE:", exc)
        return False
    if anunciar:
        print("ACTUALIZACIÓN CORRECTA: signo, tasa y valores comprobados.")
    return True


def comprobar_paso(paso, predecir, actualizar, anunciar=True):
    try:
        ps = crear_parametros()
        # El reinicio debe eliminar estos gradientes previos deliberadamente conocidos.
        for p in ps:
            p.grad = 9.0
        loss = paso(ps, 0.5)
        assert isinstance(loss, Value), "Devuelve la pérdida Value calculada antes de actualizar."
        assert math.isclose(loss.data, math.log(2), abs_tol=1e-12), "La pérdida del lote debe ser una media escalar."
        assert all(math.isclose(g, w, abs_tol=1e-12) for g, w in zip(gradientes(ps), (0, 0, 0.25))), "Revisa reinicio, backward y media del lote."
        assert all(math.isclose(g, w, abs_tol=1e-12) for g, w in zip(valores(ps), (0, 0, -0.125))), "Revisa orden del ciclo y actualización de los parámetros."
        # Segunda iteración desde otros valores; evita aceptar respuestas memorizadas.
        q = crear_parametros(0.3, -0.1, -0.4)
        initial = valores(q)
        expected_g = [0.0]*3
        for x1, x2, y in DATOS_AND:
            pred = 1/(1+math.exp(-(initial[0]*x1+initial[1]*x2+initial[2])))
            for j, v in enumerate((x1, x2, 1)):
                expected_g[j] += (pred-y)*v/4
        paso(q, 0.2)
        assert all(math.isclose(p.data, v-0.2*g, abs_tol=1e-12) for p, v, g in zip(q, initial, expected_g)), "El ciclo debe usar los valores actuales, no los del ejemplo resuelto."
    except ActividadPendiente as exc:
        if anunciar:
            print("PENDIENTE:", exc)
        return False
    if anunciar:
        print("CICLO CORRECTO: reinicio, forward, pérdida, backward y actualización.")
    return True


def entrenar(paso, predecir, parametros, tasa=TASA, iteraciones=ITERACIONES):
    """Controlador proporcionado: llama al paso escrito por el estudiante y registra."""
    history = []
    for step in range(iteraciones):
        before = valores(parametros)
        loss = paso(parametros, tasa)
        after = valores(parametros)
        gs = gradientes(parametros)
        assert math.isfinite(loss.data) and all(math.isfinite(v) for v in (*after, *gs))
        history.append({"paso": step+1, "loss_antes": loss.data,
                        "grad_norm": math.sqrt(sum(g*g for g in gs)),
                        "change_norm": math.sqrt(sum((a-b)**2 for a, b in zip(after, before))),
                        **{f"{n}_antes": v for n, v in zip(NOMBRES, before)},
                        **{f"grad_{n}": v for n, v in zip(NOMBRES, gs)},
                        **{f"{n}_despues": v for n, v in zip(NOMBRES, after)}})
    return history


def guardar_resultados(history, filas, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("traza_entrenamiento.csv", history), ("tabla_and.csv", filas)):
        with (output_dir / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    import matplotlib.pyplot as plt
    with plt.rc_context({"font.size": 11}):
        fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), layout="constrained")
        steps = [r["paso"] for r in history]
        axes[0].plot(steps, [r["loss_antes"] for r in history], color="#3155a4")
        axes[0].set(xlabel="Paso", ylabel="Pérdida media antes del paso", title="Objetivo de entrenamiento")
        for n in NOMBRES:
            axes[1].plot(steps, [r[f"{n}_despues"] for r in history], label=n,
                         linestyle="--" if n == "w2" else "-", linewidth=2)
        axes[1].set(xlabel="Paso", ylabel="Valor después del paso", title="Parámetros: w1 y w2 coinciden")
        axes[1].legend()
        for ax in axes:
            ax.grid(alpha=0.2)
        fig.savefig(output_dir / "entrenamiento_and.png", dpi=160)
        from IPython.display import Image, display
        display(Image(filename=str(output_dir / "entrenamiento_and.png")))
        plt.close(fig)


def validar_final(predecir, actualizar, paso, history, parametros):
    assert comprobar_forward(predecir, False)
    assert comprobar_actualizacion(actualizar, False)
    assert comprobar_paso(paso, predecir, actualizar, False)
    assert len(history) == ITERACIONES, f"Se requieren {ITERACIONES} pasos con la configuración proporcionada."
    assert all(row["correcta"] for row in evaluar(predecir, parametros)), "Comprueba las cuatro combinaciones AND."
    assert perdida_lote(predecir, parametros).data < history[0]["loss_antes"], "La pérdida final debe ser menor que la inicial."
    assert all(math.isclose(r["change_norm"], TASA*r["grad_norm"], abs_tol=1e-11) for r in history), "Revisa el cambio de parámetros en cada paso."
    return True
