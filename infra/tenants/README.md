# Per-tenant configuration

One codebase, many configurations. The Terraform **code** lives in
`infra/scheduler` and `infra/modules` and is identical for every tenant. Only
the files here differ per tenant.

For each tenant, create two files (copy the `.example` templates):

| File | Purpose |
|---|---|
| `<tenant>.tfvars` | Tenant-specific input variables (subscription, scopes, emails) |
| `<tenant>.backend.hcl` | Tenant-specific Terraform **state backend** (isolated state) |

Example:

```bash
cp example.tfvars.example        contoso.tfvars
cp example.backend.hcl.example   contoso.backend.hcl
# edit both for the Contoso tenant
```

Then deploy with the wrapper from the repo root:

```bash
./infra/deploy.sh contoso plan
./infra/deploy.sh contoso apply
```

## Rules

- **Real `*.tfvars` and `*.backend.hcl` are gitignored.** Only the `*.example`
  templates are committed. This keeps tenant identifiers out of version control.
- **Isolated state per tenant.** Each `<tenant>.backend.hcl` points at a state
  storage account inside that tenant's own management subscription. Tenants
  never share state and never access each other.
- **Do not use git branches per tenant.** Keep one `main` branch; tenants are
  distinguished by these config files, not by branches.
- **Production is always hard-excluded** in every tenant (BR-003): subscriptions
  tagged `environment=prod` are never acted on.
