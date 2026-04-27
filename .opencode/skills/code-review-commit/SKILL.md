---
name: code-review-commit
description: >
  Skill para revisión de código React, gestión de ramas git y creación de
  commits siguiendo el estándar Conventional Commits. Decide cuándo crear una
  nueva rama basándose en la complejidad del cambio, revisa calidad de código
  React y genera mensajes de commit profesionales.
version: 1.0.0
author: OpenCode Agent
language: es
tags:
  - react
  - git
  - code-review
  - conventional-commits
  - branch-management
---

# Code Review & Commit Skill

## Objetivo

Actuar como un senior developer especializado en React y flujos de trabajo git.
Revisar código, decidir si es necesario crear una nueva rama, y generar commits
siguiendo el estándar Conventional Commits.

---

## Flujo de Trabajo

Sigue este flujo **en orden** cada vez que se active esta skill:

### 1. Análisis del Estado del Repositorio

- Ejecuta `git status` para ver cambios staged, unstaged y untracked.
- Ejecuta `git branch --show-current` para saber en qué rama estamos.
- Ejecuta `git diff --stat` para ver el resumen de cambios.
- Si hay archivos staged, ejecuta `git diff --staged` para ver los cambios a
  commit.

### 2. Decisión: ¿Nueva Rama?

**Debes crear una nueva rama SI se cumple AL MENOS una de estas condiciones:**

- Hay cambios en **5 o más archivos**.
- Se está implementando una **nueva feature** compleja (ej: autenticación,
  dashboard, formulario multistep).
- Los cambios introducen un **breaking change**.
- Se está en la rama `main` o `master` y los cambios no son un hotfix
  trivial.
- Los cambios afectan lógica crítica (routing, state management global,
  API calls core).

**Convención de nombres para ramas:**

```
feature/descripcion-corta-en-kebab-case
fix/descripcion-del-bug-en-kebab-case
refactor/nombre-del-componente-o-area
chore/tarea-de-mantenimiento
docs/actualizacion-documentacion
test/adicion-tests-componente
```

**Ejemplos:**

- `feature/user-auth-login`
- `fix/header-responsive-mobile`
- `refactor/extract-useForm-hook`

**Si decides crear rama:**

1. Sugiere el nombre de la rama al usuario con la convención anterior.
2. Ejecuta `git checkout -b <nombre-rama>`.
3. Informa al usuario que se ha creado y cambiado a la nueva rama.

**Si NO es necesaria nueva rama:**

- Continúa en la rama actual y justifica brevemente por qué no es necesario.

### 3. Revisión de Código (React)

Revisa **todos los archivos modificados** (staged y unstaged relevantes) con
estos criterios:

#### 3.1 Estructura y Naming

- Componentes en **PascalCase** (ej: `UserCard`, `LoginForm`).
- Hooks personalizados empiezan con **use** (ej: `useAuth`, `useForm`).
- Funciones auxiliares en **camelCase**.
- Archivos de componente coinciden con el nombre del componente.

#### 3.2 Hooks y Lifecycle

- Verificar **reglas de hooks**: solo llamados en top-level de componentes o
  custom hooks, nunca en loops, condiciones o funciones anidadas.
- Revisar **dependencias de `useEffect`**: deben incluir todas las variables
  usadas dentro. Advertir si faltan o sobran.
- `useEffect` debe tener función de cleanup cuando se suscriba a eventos,
  timers o conexiones.
- Evitar `useEffect` para lógica que puede resolverse en event handlers o
  durante render.

#### 3.3 Estado y Props

- No mutar estado directamente (usar siempre el setter o función de update).
- Props destructuradas para claridad.
- `key` props únicas y estables en listas (evitar índices si los items
  pueden reordenarse).
- Default props o default parameters en desestructuración.

#### 3.4 Performance

- Usar `React.memo` para componentes que reciben props complejas pero se
  renderizan con los mismos valores frecuentemente.
- Usar `useMemo` para cálculos costosos.
- Usar `useCallback` para funciones pasadas como props a componentes hijos
  memoizados.
- Evitar premature optimization: no memoizar todo sin medir.

#### 3.5 Manejo de Errores y UX

- Loading states visibles para operaciones asíncronas.
- Manejo de errores con try/catch o .catch en promises.
- No dejar `console.log` en código de producción.
- Evitar `alert()` nativo; usar notificaciones del sistema de UI.

#### 3.6 TypeScript (si aplica)

- Tipos explícitos en props de componentes (interfaces preferidas sobre
  types para objetos).
- Evitar `any`. Usar `unknown` si es necesario y hacer type narrowing.
- Genericos usados correctamente en custom hooks y utilidades.

#### 3.7 Accesibilidad (a11y)

- Imágenes con `alt` descriptivo.
- Botones y links interactivos con roles correctos.
- Formularios con `label` asociados a inputs (`htmlFor`).
- Contraste de colores considerado.

### 4. Generación del Mensaje de Commit

Una vez aprobada la calidad del código (o si el usuario decide proseguir
a pesar de warnings), genera el mensaje de commit.

#### Estándar Conventional Commits

```
<tipo>(<alcance opcional>): <descripción>

<cuerpo opcional>

<footer opcional>
```

#### Tipos Permitidos

| Tipo       | Uso                                                                 |
|------------|----------------------------------------------------------------------|
| `feat`     | Nueva feature o funcionalidad                                        |
| `fix`      | Corrección de bug                                                    |
| `docs`     | Cambios solo en documentación                                        |
| `style`    | Cambios de formato (espacios, comas, etc.) sin cambio de lógica     |
| `refactor` | Refactorización de código sin cambiar funcionalidad externa          |
| `perf`     | Cambios que mejoran performance                                      |
| `test`     | Añadir o corregir tests                                              |
| `chore`    | Tareas de mantenimiento (build, deps, config, etc.)                  |
| `ci`       | Cambios en CI/CD                                                     |
| `revert`   | Revertir un commit previo                                            |

#### Reglas del Mensaje

- **Descripción**: en imperativo presente ("add", "fix", "update", NO
  "added", "fixed").
- **Descripción**: primera letra minúscula, sin punto final.
- **Alcance**: nombre del componente, módulo o área afectada (ej:
  `(auth)`, `(header)`, `(hooks)`).
- **Cuerpo**: explicar el "por qué" del cambio, no solo el "qué". Usar
  líneas de máximo 72 caracteres.
- **Breaking changes**: añadir `!` después del tipo/alcance, o incluir
  `BREAKING CHANGE:` en el footer.

#### Ejemplos

```
feat(auth): add login form with validation

Implements email/password validation using react-hook-form.
Adds error handling and loading state for UX feedback.
```

```
fix(hooks): resolve useEffect dependency in useAuth

Missing dependency caused stale closure on token refresh.
Added token to dependency array and memoized with useCallback.
```

```
refactor(utils): extract formatDate helper

Reduces duplication across Dashboard and Reports components.
No functional changes.
```

```
feat(api)!: remove v1 endpoints support

BREAKING CHANGE: All API calls must now use /api/v2 prefix.
Migration guide updated in MIGRATION.md.
```

### 5. Ejecución del Commit

1. Si no están staged todos los archivos relevantes, preguntar al usuario
   cuáles quiere incluir.
2. Mostrar el mensaje de commit propuesto.
3. Preguntar al usuario si quiere proceder, modificar el mensaje, o cancelar.
4. Si el usuario aprueba, ejecutar:
   ```bash
   git commit -m "<mensaje>"
   ```
   (Si tiene cuerpo/footer multilínea, usar `git commit` sin `-m` y dejar
   que se abra el editor, o usar heredoc).

### 6. Post-Commit

- Resumir lo que se hizo (rama creada, archivos commiteados, tipo de cambio).
- Si hay más cambios pendientes, ofrecer hacer otro commit o revisarlos.
- **Nunca hacer `git push` automáticamente.** Siempre preguntar antes.

---

## Restricciones Importantes

- **No hacer push automáticamente.** Siempre confirmar con el usuario.
- **No hacer force push** bajo ninguna circunstancia a menos que el usuario
  lo solicite explícitamente.
- **No modificar código** sin permiso del usuario; solo sugerir cambios en
  la revisión.
- **No hacer amend** a commits ya pusheados sin avisar explícitamente del
  riesgo.
- Si el usuario rechaza crear una nueva rama cuando tú la recomiendas,
  respetar su decisión pero documentar el riesgo.

---

## Ejemplo de Interacción Completa

```
Usuario: revisa y commitea mis cambios

Agente:
1. Ejecuta git status, git branch, git diff --stat
2. Detecta 8 archivos modificados en main
3. Recomienda: "Los cambios son extensos (8 archivos) y estamos en main.
   Sugiero crear una rama: feature/dashboard-redesign"
4. Usuario: ok
5. Agent: git checkout -b feature/dashboard-redesign
6. Revisa código: revisa cada archivo, reporta:
   - WARNING: useEffect en Dashboard.jsx falta dependency 'filters'
   - OK: Componentes bien nombrados
   - SUGERENCIA: Extraer lógica de fetch a custom hook useDashboard
7. Mensaje propuesto:
   feat(dashboard): redesign layout with filters and pagination

   Adds responsive grid layout, filter sidebar and paginated data table.
   Introduces useDashboard hook to manage data fetching and state.
8. Usuario: aprobar
9. Agent: git commit -m "feat(dashboard): redesign layout with filters and pagination"
10. Resumen final del commit.
```

---
