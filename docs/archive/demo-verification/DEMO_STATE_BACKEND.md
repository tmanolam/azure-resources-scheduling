# Demo State: Migrate to a Remote Backend

> 🗄️ **Archived on 2026-10-07.** Record of the one-time migration of the demo
> Terraform roots to the remote azurerm backend (`demosatfstate`), completed
> 2026-10-06. Kept as the reference for how the demo state is wired; it stays
> relevant to the still-deployed demo infrastructure in
> [`demo/`](../../../demo/README.md) until the demo is torn down. No longer updated.

| Item | Value |
|---|---|
| Document ID | AZ-PWRSCHED-DEMO-STATE-001 |
| Status | **Done** (2026-10-06). Both roots migrated to the remote azurerm backend (`demosatfstate`). |
| Related | [DEMO_TENANT_PLAN.md](DEMO_TENANT_PLAN.md), [../../../demo/README.md](../../../demo/README.md), [../../../infra/tenants/demo.backend.hcl.example](../../../infra/tenants/demo.backend.hcl.example) |
| Created | 2026-10-06 |

## Why

The two demo Terraform roots previously used **local state**:

- `demo/landing-zone/` — MG hierarchy, subscription placement, tags, budgets
- `demo/workloads/` — W1–W14

That state lived on whichever laptop ran the applies. This caused **split-brain
state**: a second laptop that runs `terraform plan`/`apply` initialises an
**empty** local state and plans to **recreate everything** (or errors with
"already exists"). The sandbox onboarding (2026-10-06) hit exactly this — the
applies had to be run on the laptop holding the state.

Both roots are now on a **remote azurerm backend** (the same storage account the
shipped scheduler already uses for the demo tenant), so any authorised machine
can run the demo safely, with state locking.

> The shipped product (`infra/scheduler`) is already remote (via
> `./infra/deploy.sh demo`, backend `infra/tenants/demo.backend.hcl`). This change
> brings the two **demo-only** roots in line.

## Design

Reuse the demo state storage account from `infra/tenants/demo.backend.hcl`
(account `demosatfstate`, RG `rg-tfstate-demo`, container `tfstate`) with a
**distinct key per root**:

| Root | Backend key |
|---|---|
| `infra/scheduler` (existing) | `pwrsched/demo.tfstate` |
| `demo/landing-zone` (new) | `demo/landing-zone.tfstate` |
| `demo/workloads` (new) | `demo/workloads.tfstate` |

Templates are committed:
- `demo/landing-zone/backend.hcl.example`
- `demo/workloads/backend.hcl.example`

The `backend "azurerm" {}` blocks are **uncommented** (active) in each root's
`providers.tf`. Real `backend.hcl` files are gitignored (only the `.example`
templates are committed).

## Procedure (one-time, per root)

> ✅ **Completed 2026-10-06** for both roots from the operator laptop holding
> the local state. The steps below are retained as a reference (e.g. if the
> backend is ever re-created). The `backend.hcl` files now exist and the
> backend blocks in `providers.tf` are active.

> ⚠️ **Run from the laptop that currently holds the local state.** Migration
> copies the existing local state up to the backend. Running `init -migrate-state`
> from a laptop **without** the local state starts empty and will plan to
> recreate all resources — do not do that.

Pre-check the state account is reachable in the demo tenant:

```bash
az login --tenant <demo-tenant-id>
export ARM_SUBSCRIPTION_ID=<demo-management-subscription-id>
az storage account show -n demosatfstate -g rg-tfstate-demo -o none   # should succeed
```

For each root (`demo/landing-zone`, then `demo/workloads`):

```bash
cd demo/landing-zone        # then repeat in demo/workloads

# 1. Uncomment the `backend "azurerm" {}` line in providers.tf
# 2. Create the real backend config from the template
cp backend.hcl.example backend.hcl     # edit if the account/RG/container differ

# 3. Migrate the existing LOCAL state up to the remote backend
terraform init -migrate-state -backend-config=backend.hcl
#    Terraform detects local state and asks:
#      "Do you want to copy existing state to the new backend?"  →  yes

# 4. Sanity check: no changes expected
terraform plan      # must report: No changes. (If it wants to create everything,
                    #   STOP — the wrong/empty state was used.)
```

After migration, on **any** authorised machine:

```bash
cd demo/landing-zone
terraform init -reconfigure -backend-config=backend.hcl
terraform plan
```

## Verification

- [x] `demo/landing-zone`: `terraform state list` → 22 resources from remote backend
- [x] `demo/workloads`: `terraform state list` → 46 resources from remote backend
- [ ] A second machine can `init -reconfigure` + `plan` with the same result
- [x] State blobs exist: `demo/landing-zone.tfstate` and `demo/workloads.tfstate`
      in container `tfstate` of `demosatfstate`
- [ ] Local `terraform.tfstate` files removed (or left as a one-off backup, not committed)

## Rollback

The migration only copies state; live resources are untouched. To revert to
local state before anyone else uses the remote state: re-comment the backend
block and run `terraform init -migrate-state` again (copies the remote state
back down). Once a second machine has used the remote state, prefer staying
remote to avoid divergence.

## Notes

- Keep each root's key distinct (above); never point two roots at the same key.
- `use_azuread_auth = true` matches the scheduler backend; the operator needs
  **Storage Blob Data Contributor** on `demosatfstate` (same as README Step 2).
- Teardown (DEMO_TENANT_PLAN §9) is unaffected: destroy from the machine that has
  backend access; delete the demo-only state account/blobs last.
