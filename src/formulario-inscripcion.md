# Formulario de inscripción

**Título:** Inscripción
**Descripción:** Completa tus datos para inscribirte.

## Preguntas

Todas son obligatorias.

| # | Pregunta | Tipo en Google Forms | Detalle |
|---|----------|----------------------|---------|
| 1 | Nombre | Respuesta corta | — |
| 2 | Apellido | Respuesta corta | — |
| 3 | Número de celular | Respuesta corta | Validación: Expresión regular → Coincide → `[0-9]{9}`. Mensaje: "Ingresa 9 dígitos, sin espacios." |
| 4 | Ciclo | Menú desplegable | Opciones: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| 5 | Universidad | Respuesta corta | — |

## Opción A: crearlo automáticamente

1. Entra a <https://script.google.com> y crea un **Proyecto nuevo**.
2. Pega el contenido de [`crear-formulario.gs`](crear-formulario.gs) y guarda.
3. Ejecuta la función `crearFormulario` y acepta los permisos.
4. En el registro de ejecución aparecen dos enlaces:
   - **Enlace público**: es el que compartes con los participantes.
   - **Enlace de edición**: es solo para ti.

## Opción B: crearlo a mano

1. Entra a <https://forms.google.com> y crea un formulario en blanco.
2. Agrega las 5 preguntas de la tabla y marca todas como **Obligatorio**.

## Hacerlo público

1. Pulsa **Publicar** (arriba a la derecha) y confirma.
2. En **Responder**, copia el enlace y compártelo.
3. En **Configuración → Respuestas**, revisa que **Restringir a usuarios de la organización** y **Limitar a 1 respuesta** estén **desactivados**. Así cualquiera con el enlace puede responder sin iniciar sesión.

Si creas el formulario con una cuenta institucional (por ejemplo `@uni.pe`), el administrador del dominio puede forzar la restricción a la organización. En ese caso usa una cuenta Gmail personal.
