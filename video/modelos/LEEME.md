# Modelos de pelota

Los `.onnx` no entran al repo (`.gitignore`). Se bajan y verifican con:

```
python -m video modelos
```

| Nombre | Archivo | SHA-256 | Tamaño |
|---|---|---|---|
| `v4c` | `VballNetV4c_seq9_grayscale_20260908_213829.onnx` | `8eea11cc5c881fa008ec55b0f5732ab79f2e0e1833d7f586e680f3aaa98e4b8c` | 987 155 |
| `fastv1` | `VballNetFastV1_seq9_grayscale_233_h288_w512.onnx` | `a37d2f082c1821c31da10b4d3356788ed8ec0e1ba1c7d4fcbaf69f76925b0ff8` | 50 199 |

**Origen:** [asigatchov/fast-volleyball-tracking-inference](https://github.com/asigatchov/fast-volleyball-tracking-inference),
carpeta `models/` en el commit `c3864156a4dfbd5af3f00f427ab0fc4bfe7af5b5`
(12/11/2026). Licencia MIT, que según su README cubre también los pesos.

**Qué esperan:** 9 cuadros seguidos en gris, achicados a 512×288, con valores
de 0 a 1 (`[1, 9, 288, 512]`). **Qué devuelven:** un mapa de calor por cuadro
(`v4c` además devuelve 9 mapas de radio después de los 9 de calor).

Los entrenó su autor con vóley de playa. Lo que valen con nuestros videos lo
mide `python -m video probar-pelota`, no su tabla.
