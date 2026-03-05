# Plan: Rebranding Dify → SebasAgent (Frontend Web — Fase 2)

**Date**: 2026-03-05
**Complexity**: medium
**Estimated time**: 25 min

## Contexto
El commit c6fd49ed9e cubrió i18n strings y componentes principales.
Esta fase 2 elimina todas las URLs y referencias a `dify.ai` que quedaron hardcodeadas en componentes TSX/TS y en el archivo workflow.json de i18n.

## Acceptance Criteria
- [ ] Ningún `href` visible en UI apunta a `*.dify.ai` o `dify.ai/*`
- [ ] El email de soporte no es `support@dify.ai`
- [ ] El footer no enlaza al GitHub de langgenius/dify
- [ ] `context/i18n.ts` no usa `docs.dify.ai` como base de documentación
- [ ] `workflow.json` en-US no menciona `support@dify.ai`
- [ ] Todos los archivos modificados son JSON válido (para los i18n)

## Estrategia de URLs
| URL original | Reemplazado por |
|---|---|
| `https://forum.dify.ai` | `#` |
| `https://roadmap.dify.ai` | `#` |
| `https://docs.dify.ai` | `#` |
| `https://cloud.dify.ai/apps` | `#` |
| `https://dify.ai` | `https://sebasagent.com` |
| `https://dify.ai/privacy` | `#` |
| `https://dify.ai/terms` | `#` |
| `https://dify.ai/pricing*` | `#` |
| `https://github.com/langgenius/dify` | `#` |
| `support@dify.ai` | `soporte@sebasagent.com` |

---

## Tasks

### Task 1 — Support email y util.ts
**Agent**: frontend-ux-expert
**Files**:
- `web/app/components/header/utils/util.ts`
- `web/app/components/workflow/nodes/human-input/components/delivery-method/method-selector.tsx`

**Steps**:
1. En `util.ts` línea 24: cambiar `'support@dify.ai'` → `'soporte@sebasagent.com'`
2. En `method-selector.tsx` línea 212: cambiar `href="mailto:support@dify.ai"` y el texto `support@dify.ai` → `soporte@sebasagent.com`

**Verification**: `grep -rn "support@dify.ai" web/app/components/header/utils/util.ts web/app/components/workflow/nodes/human-input/`

---

### Task 2 — Header dropdown: forum y roadmap
**Agent**: frontend-ux-expert
**Files**:
- `web/app/components/header/account-dropdown/support.tsx`
- `web/app/components/header/account-dropdown/index.tsx`

**Steps**:
1. En `support.tsx` línea 90: `href="https://forum.dify.ai/"` → `href="#"`
2. En `index.tsx` línea 157: `href="https://roadmap.dify.ai"` → `href="#"`

**Verification**: `grep -n "dify.ai" web/app/components/header/account-dropdown/support.tsx web/app/components/header/account-dropdown/index.tsx`

---

### Task 3 — Footer (forum + GitHub langgenius)
**Agent**: frontend-ux-expert
**Files**:
- `web/app/components/apps/footer.tsx`

**Steps**:
1. Línea 35: `href="https://github.com/langgenius/dify"` → `href="#"`
2. Línea 41: `href="https://forum.dify.ai"` → `href="#"`

**Verification**: `grep -n "dify" web/app/components/apps/footer.tsx`

---

### Task 4 — Account About: privacy + terms links
**Agent**: frontend-ux-expert
**Files**:
- `web/app/components/header/account-about/index.tsx`

**Steps**:
1. Línea 65: `href="https://dify.ai/privacy"` → `href="#"`
2. Línea 67: `href="https://dify.ai/terms"` → `href="#"`

**Verification**: `grep -n "dify.ai" web/app/components/header/account-about/index.tsx`

---

### Task 5 — Auth pages: signin, signup, forgot-password, activate
**Agent**: frontend-ux-expert
**Files**:
- `web/app/signin/normal-form.tsx` (líneas 249, 258)
- `web/app/signin/invite-settings/page.tsx` (línea 79)
- `web/app/signup/components/input-mail.tsx` (líneas 102, 111)
- `web/app/forgot-password/ChangePasswordForm.tsx` (línea 93)
- `web/app/activate/activateForm.tsx` (línea 63)
- `web/app/(shareLayout)/webapp-signin/normalForm.tsx` (líneas 180, 189)

**Steps**:
1. Todos los `href="https://dify.ai/terms"` → `href="#"`
2. Todos los `href="https://dify.ai/privacy"` → `href="#"`
3. `href="https://dify.ai"` (en invite-settings, forgot-password, activate) → `href="https://sebasagent.com"`

**Verification**: `grep -rn "dify.ai" web/app/signin/ web/app/signup/ web/app/forgot-password/ web/app/activate/ "web/app/(shareLayout)/webapp-signin/"`

---

### Task 6 — App overview: settings + apikey-info-panel
**Agent**: frontend-ux-expert
**Files**:
- `web/app/components/app/overview/settings/index.tsx` (línea 405)
- `web/app/components/app/overview/apikey-info-panel/index.tsx` (línea 60)

**Steps**:
1. En `settings/index.tsx` línea 405: `href="https://dify.ai/privacy"` → `href="#"`
2. En `apikey-info-panel/index.tsx` línea 60: `href="https://cloud.dify.ai/apps"` → `href="#"`

**Verification**: `grep -rn "dify.ai" web/app/components/app/overview/`

---

### Task 7 — Billing pricing + Delete account pages
**Agent**: frontend-ux-expert
**Files**:
- `web/app/components/billing/pricing/index.tsx` (líneas 40-41)
- `web/app/account/(commonLayout)/delete-account/components/check-email.tsx` (línea 38)
- `web/app/account/(commonLayout)/delete-account/components/verify-email.tsx` (línea 44)
- `web/app/education-apply/education-apply-page.tsx` (líneas 130, 134)

**Steps**:
1. En `pricing/index.tsx`: cambiar URLs de pricing a `'#'` (las dos líneas de la ternaria)
2. En `check-email.tsx` y `verify-email.tsx`: `href="https://dify.ai/privacy"` → `href="#"`
3. En `education-apply-page.tsx`: ambos dify.ai links → `href="#"`

**Verification**: `grep -rn "dify.ai" web/app/components/billing/ web/app/account/ web/app/education-apply/`

---

### Task 8 — context/i18n.ts + i18n/en-US/workflow.json
**Agent**: frontend-ux-expert
**Files**:
- `web/context/i18n.ts` (línea 24)
- `web/i18n/en-US/workflow.json` (línea 510)

**Steps**:
1. En `i18n.ts` línea 24: `'https://docs.dify.ai'` → `'#'`
2. En `workflow.json` línea 510: `support@dify.ai` → `soporte@sebasagent.com` (en el string y en el href)

**Verification**:
- `grep -n "dify.ai" web/context/i18n.ts`
- `grep -n "dify.ai" web/i18n/en-US/workflow.json`
- `python3 -c "import json; json.load(open('web/i18n/en-US/workflow.json'))" && echo "JSON válido"`

---

### Task 9 — Verificación final completa
**Agent**: platform-expert
**Files**: todos los anteriores

**Steps**:
1. Ejecutar grep global para confirmar que no quedan referencias user-visible a dify.ai:
   ```
   grep -rn "dify\.ai" web/app/ web/context/ web/i18n/en-US/ \
     --include="*.tsx" --include="*.ts" --include="*.json" \
     --exclude-dir=node_modules --exclude="*.spec.*" --exclude="*.d.ts"
   ```
2. Verificar JSON válido en todos los archivos i18n modificados

**Verification**: salida del grep debe estar vacía (o solo contener archivos de spec/test que no son user-facing)
