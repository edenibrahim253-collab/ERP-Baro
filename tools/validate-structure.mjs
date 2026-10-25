// Structural validator for the baro_core Frappe app.
//
// There is no Python, MariaDB or bench on this machine, so the app cannot be executed here.
// This script is what can be checked without a runtime: that every JSON file parses, that every
// reference between files resolves to something that exists, that the design documents and the
// schema agree, and that the two hard project rules (the automation boundary and the single
// writer of the UQ-DRV columns) are not broken by a stray call.
//
// Run: node tools/validate-structure.mjs [--verbose]

import fs from "node:fs";
import path from "node:path";

const ROOT = process.cwd();
const APP = path.join(ROOT, "baro_core", "baro_core");
const DOCS = path.join(ROOT, "docs");
const verbose = process.argv.includes("--verbose");

const checks = [];
let failures = 0;

function report(name, problems, notes = []) {
  checks.push({ name, problems, notes });
  failures += problems.length;
}
const push = (arr, msg) => arr.push(msg);

function walk(dir, filter) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(p, filter));
    else if (filter(p)) out.push(p);
  }
  return out;
}
const rel = (p) => path.relative(ROOT, p).replace(/\\/g, "/");
const read = (p) => fs.readFileSync(p, "utf8");

const pyFiles = walk(APP, (p) => p.endsWith(".py"));
const jsonFiles = walk(APP, (p) => p.endsWith(".json"));
const docFiles = fs.existsSync(DOCS) ? walk(DOCS, (p) => p.endsWith(".md")) : [];

function fixture(name) {
  const p = path.join(APP, "fixtures", `${name}.json`);
  if (!fs.existsSync(p)) return [];
  const data = JSON.parse(read(p));
  return Array.isArray(data) ? data : [];
}
const ROLE_NAMES = new Set(fixture("role").map((r) => r.name).filter(Boolean));

// ---------------------------------------------------------------- 1. JSON parses
{
  const problems = [];
  for (const p of jsonFiles) {
    try {
      JSON.parse(read(p));
    } catch (e) {
      push(problems, `${rel(p)}: ${e.message}`);
    }
  }
  report("every JSON file parses", problems);
}

// ---------------------------------------------------------------- 2. DocType shape
const doctypes = new Map(); // name -> {json, path, fields:Map}
const childDoctypes = new Set();
{
  const problems = [];
  for (const p of jsonFiles) {
    const j = JSON.parse(read(p));
    if (!j.doctype || !j.fields) continue;
    if (j.doctype !== "DocType") continue; // fixture records are checked in their own section
    if (j.name === j.doctype) push(problems, `${rel(p)}: DocType file whose name is "DocType"`);
    doctypes.set(j.name, { json: j, path: p, fields: new Map(j.fields.map((f) => [f.fieldname, f])) });
    if (j.istable) childDoctypes.add(j.name);
    const seen = new Set();
    for (const f of j.fields) {
      if (seen.has(f.fieldname)) push(problems, `${j.name}: duplicate fieldname ${f.fieldname}`);
      seen.add(f.fieldname);
      if (!/^[a-z][a-z0-9_]*$/.test(f.fieldname)) {
        push(problems, `${j.name}: fieldname ${f.fieldname} is not snake_case`);
      }
      if (f.fieldtype === "Link" && !f.options) push(problems, `${j.name}.${f.fieldname}: Link without options`);
      if (f.fieldtype === "Select" && !f.options) push(problems, `${j.name}.${f.fieldname}: Select without options`);
      if (f.fieldtype === "Table" && f.options && !childDoctypes.has(f.options) && !doctypes.has(f.options)) {
        push(problems, `${j.name}.${f.fieldname}: table child ${f.options} not defined in this app`);
      }
    }
    const order = j.field_order || [];
    for (const name of order) if (!seen.has(name)) push(problems, `${j.name}: field_order lists unknown field ${name}`);
    for (const name of seen) if (order.length && !order.includes(name)) push(problems, `${j.name}: ${name} missing from field_order`);
    if (j.autoname && String(j.autoname).startsWith("field:")) {
      const f = String(j.autoname).slice(6);
      if (!seen.has(f)) push(problems, `${j.name}: autoname ${j.autoname} references unknown field`);
    }
    // docs/41 §5.1: a record-scoped DocType must actually opt into User Permissions
    if (j.fields.some((f) => f.fieldtype === "Link" && f.options === "Customer") && !j.apply_user_permissions) {
      push(problems, `${j.name}: links Customer but apply_user_permissions is not set (docs/41 §5.1)`);
    }
    if (j.issingle && j.naming_series) push(problems, `${j.name}: a Single cannot carry a naming series`);
    // controller file must exist and define the class
    const slug = path.basename(p, ".json");
    const controller = path.join(path.dirname(p), `${slug}.py`);
    if (!fs.existsSync(controller)) push(problems, `${j.name}: missing controller ${rel(controller)}`);
    else if (!new RegExp(`class ${j.name.replace(/ /g, "")}\\b`).test(read(controller))) {
      push(problems, `${j.name}: controller does not define class ${j.name.replace(/ /g, "")}`);
    }
  }
  report("DocType JSON shape, field_order, controllers", problems);
}

// ---------------------------------------------------------------- 3. naming series
{
  const problems = [];
  for (const [name, dt] of doctypes) {
    const series = dt.fields.get("naming_series");
    if (series && series.options) {
      for (const s of series.options.split("\n").filter(Boolean)) {
        if (!/^BARO-[A-Z]+-?\.####$/.test(s)) push(problems, `${name}: naming series ${s} is not BARO-*.####`);
      }
    }
    if (dt.json.autoname === "naming_series:" && !series) push(problems, `${name}: autoname promises a series but no naming_series field`);
  }
  report("BARO-*.#### naming series", problems);
}

// ---------------------------------------------------------------- 4. Link targets resolve
const STD_LINKS = new Set([
  "DocType", "User", "Role", "File", "Company", "Customer", "Item", "Item Group", "Warehouse",
  "Supplier", "Serial No", "Installation Note", "Quality Inspection", "Issue", "Task", "Project",
  "Employee", "Appointment", "Subscription", "Subscription Plan", "Sales Invoice", "Asset",
  "Contract", "Warranty Claim", "UOM", "Currency", "Territory", "Customer Group", "Contact",
  "Address", "Price List", "Department", "Designation", "Lead", "Opportunity", "Quotation",
  "Sales Order", "Delivery Note", "Purchase Order", "Purchase Invoice", "Stock Entry",
]);
{
  const problems = [];
  const check = (dtName, f, value) => {
    if (!value) return;
    if (doctypes.has(value) || STD_LINKS.has(value)) return;
    push(problems, `${dtName}.${f}: link/option target "${value}" is neither defined here nor a known standard DocType`);
  };
  for (const [name, dt] of doctypes) {
    for (const [fieldname, f] of dt.fields) {
      // Dynamic Link stores the *fieldname* that holds the DocType, not a DocType name
      if (["Link", "Table MultiSelect", "Table"].includes(f.fieldtype)) check(name, fieldname, f.options);
    }
    for (const perm of dt.json.permissions || []) {
      if (perm.role && ROLE_NAMES.size && !ROLE_NAMES.has(perm.role) && perm.role.startsWith("BARO ")) {
        push(problems, `${name}: DocPerm role "${perm.role}" is not in fixtures/role.json`);
      }
    }
  }
  const cf = fixture("custom_field");
  for (const row of cf) {
    if (row.fieldtype === "Link") check(row.dt, row.fieldname, row.options);
  }
  report("Link targets resolve to a real DocType", problems);
}

// ---------------------------------------------------------------- 5. fixtures <-> hooks, roles
{
  const problems = [];
  const roles = fixture("role");
  for (const r of roles) {
    if (!r.name) push(problems, `role fixture row without name`);
    if (r.name && !r.name.startsWith("BARO ")) push(problems, `role ${r.name} must start with "BARO "`);
  }
  const hooks = read(path.join(APP, "hooks.py"));
  for (const m of hooks.matchAll(/\{"doctype":\s*"([^"]+)"\}/g)) {
    const slug = m[1].toLowerCase().replace(/ /g, "_");
    if (!fs.existsSync(path.join(APP, "fixtures", `${slug}.json`))) {
      push(problems, `hooks.fixtures names ${m[1]} but fixtures/${slug}.json is absent`);
    }
  }
  // Role names referenced in role contexts must exist. A role typo in a DocPerm row, a workflow
  // transition or a Python role tuple silently allows nobody (docs/40 §9.1), so this is checked
  // structurally rather than by grepping every "BARO …" string, which would also catch email
  // subjects and log titles.
  for (const [name, dt] of doctypes) {
    for (const [fieldname, f] of dt.fields) {
      if (!/role$/.test(fieldname) || f.fieldtype !== "Select") continue;
      for (const opt of (f.options || "").split("\n").filter(Boolean)) {
        if (opt.startsWith("BARO ") && !ROLE_NAMES.has(opt)) {
          push(problems, `${name}.${fieldname}: option "${opt}" is not in fixtures/role.json`);
        }
      }
    }
  }
  for (const p of jsonFiles) {
    for (const [key, value] of roleKeyValues(JSON.parse(read(p)))) {
      if (/^BARO /.test(String(value)) && !ROLE_NAMES.has(value)) {
        push(problems, `${rel(p)}: ${key} = "${value}" is not in fixtures/role.json`);
      }
    }
  }
  for (const p of pyFiles) {
    const src = read(p);
    const contexts = [
      /has_role\(\s*["'](BARO [^"']+)["']/g,
      /_recipients\(\s*["'](BARO [^"']+)["']/g,
      /assigned_role\s*=\s*["'](BARO [^"']+)["']/g,
      /["'](BARO [^"']+)["'](?=[^#]*\bROLE)/g,
    ];
    for (const re of contexts) {
      for (const m of src.matchAll(re)) {
        if (!ROLE_NAMES.has(m[1])) push(problems, `${rel(p)}: role "${m[1]}" is not in fixtures/role.json`);
      }
    }
    for (const m of src.matchAll(/\w*ROLES\w*\s*=\s*[\({]([^)]*?)[\)]/gs)) {
      for (const r of m[1].matchAll(/["']BARO [^"']+["']/g)) {
        const role = r[0].slice(1, -1);
        if (!ROLE_NAMES.has(role)) push(problems, `${rel(p)}: role tuple has unknown "${role}"`);
      }
    }
  }
  const EXPECT = {
    role: "Role",
    custom_field: "Custom Field",
    property_setter: "Property Setter",
    workflow: "Workflow",
    report: "Report",
    workspace: "Workspace",
  };
  for (const [slug, want] of Object.entries(EXPECT)) {
    const rows = fixture(slug);
    if (!rows.length) push(problems, `fixtures/${slug}.json is empty`);
    for (const row of rows) {
      if (row.doctype && row.doctype !== want) push(problems, `fixtures/${slug}.json: row declares ${row.doctype}, expected ${want}`);
    }
  }
  report("fixtures present for every hooks entry; role references resolve", problems);
}

function* roleKeyValues(node, key = "") {
  if (Array.isArray(node)) {
    for (const item of node) yield* roleKeyValues(item, key);
  } else if (node && typeof node === "object") {
    for (const [k, v] of Object.entries(node)) {
      if (k === "role" || k === "assigned_role" || k === "baro_assigned_role") {
        if (typeof v === "string") yield [k, v];
      } else if (typeof v === "object") {
        yield* roleKeyValues(v, k);
      }
    }
  }
}

// ---------------------------------------------------------------- 6. workflow closure
{
  const problems = [];
  const customFields = new Map(); // dt -> Set(fieldname)
  for (const row of fixture("custom_field")) {
    if (!customFields.has(row.dt)) customFields.set(row.dt, new Set());
    customFields.get(row.dt).add(row.fieldname);
    if (!row.name || row.name !== `${row.dt}-${row.fieldname}`) {
      push(problems, `custom field ${row.dt}.${row.fieldname}: fixture name must be "<dt>-<fieldname>"`);
    }
    if (!String(row.fieldname).startsWith("baro_")) push(problems, `custom field ${row.dt}.${row.fieldname}: prefix`);
    if (doctypes.has(row.dt)) push(problems, `custom field on ${row.dt}: BARO DocTypes carry fields in JSON, not fixtures`);
  }
  for (const wf of fixture("workflow")) {
    const dt = doctypes.get(wf.document_type);
    if (!dt) {
      push(problems, `workflow ${wf.name || wf.workflow_name}: document_type ${wf.document_type} not defined`);
      continue;
    }
    const stateField = wf.workflow_state_field;
    if (!stateField || !dt.fields.has(stateField)) {
      push(problems, `workflow ${wf.name || wf.workflow_name}: state field ${stateField} missing on ${dt.json.name}`);
      continue;
    }
    const options = new Set((dt.fields.get(stateField).options || "").split("\n").filter(Boolean));
    const states = new Set();
    for (const s of wf.states || []) {
      states.add(s.state);
      if (!options.has(s.state)) push(problems, `workflow ${wf.name || wf.workflow_name}: state "${s.state}" is not in ${dt.json.name}.${stateField} options`);
    }
    for (const t of wf.transitions || []) {
      if (!states.has(t.state)) push(problems, `workflow ${wf.name || wf.workflow_name}: transition target "${t.state}" is not a declared state`);
      if (t.reference_name && !states.has(t.reference_name)) {
        push(problems, `workflow ${wf.name || wf.workflow_name}: "${t.reference_name}" -> "${t.state}" starts from an undeclared state`);
      }
      for (const r of t.allowed || []) {
        if (!ROLE_NAMES.has(r.role)) push(problems, `workflow ${wf.name || wf.workflow_name}: transition role ${r.role} is not a BARO role`);
      }
      for (const cond of [t.condition, t.allow]) {
        if (typeof cond !== "string") continue;
        for (const m of cond.matchAll(/doc\.([a-z_][a-z0-9_]*)/g)) {
          const f = m[1];
          if (!dt.fields.has(f) && !["docstatus", "owner", "creation", "modified", "name"].includes(f)) {
            push(problems, `workflow ${wf.name || wf.workflow_name}: condition references ${dt.json.name}.${f}, which does not exist`);
          }
        }
      }
    }
    // every enum value should be reachable from some transition
    for (const opt of options) {
      if (!states.has(opt)) push(problems, `workflow ${wf.name || wf.workflow_name}: ${dt.json.name}.${stateField} option "${opt}" has no workflow state`);
    }
  }
  report("workflow states are closed over the DocType enum, transitions/conditions/roles resolve", problems);
}

// ---------------------------------------------------------------- 7. property setters target real fields
{
  const problems = [];
  for (const ps of fixture("property_setter")) {
    const dt = doctypes.get(ps.doc_type);
    const cfRows = fixture("custom_field").filter((r) => r.dt === ps.doc_type);
    if (!dt && cfRows.length === 0 && !STD_LINKS.has(ps.doc_type)) {
      push(problems, `property setter targets unknown DocType ${ps.doc_type}`);
    }
    if (ps.field_name && dt && !dt.fields.has(ps.field_name) && !cfRows.some((r) => r.fieldname === ps.field_name)) {
      push(problems, `property setter ${ps.doc_type}.${ps.field_name}: field not found`);
    }
  }
  report("property setters target real DocTypes/fields", problems);
}

// ---------------------------------------------------------------- 8. reports + workspaces
{
  const problems = [];
  for (const r of fixture("report")) {
    if (r.ref_doctype && !doctypes.has(r.ref_doctype) && !STD_LINKS.has(r.ref_doctype)) {
      push(problems, `report ${r.name}: ref_doctype ${r.ref_doctype} not resolvable`);
    }
    for (const row of r.roles || []) {
      if (row.role && !ROLE_NAMES.has(row.role)) push(problems, `report ${r.name}: role ${row.role} is not a BARO role`);
    }
    if (r.query && /`tab[^`]+`/.test(r.query)) {
      for (const m of r.query.matchAll(/`tab([^`]+)`/g)) {
        if (!doctypes.has(m[1]) && !STD_LINKS.has(m[1])) push(problems, `report ${r.name}: SQL table tab${m[1]} is not a known DocType`);
      }
    }
  }
  for (const w of fixture("workspace")) {
    const content = typeof w.content === "string" ? JSON.parse(w.content) : w.content;
    const links = content && content.pages ? content.pages.flatMap((p) => (p.cards || []).map((c) => c.link_to)) : [];
    for (const l of links.filter(Boolean)) {
      if (!doctypes.has(l) && !STD_LINKS.has(l)) push(problems, `workspace ${w.title}: card link_to ${l} not resolvable`);
    }
    for (const row of w.for_role || []) {
      if (row.role && !ROLE_NAMES.has(row.role)) push(problems, `workspace ${w.title}: role ${row.role} is not a BARO role`);
    }
  }
  report("report SQL and workspace links resolve", problems);
}

// ---------------------------------------------------------------- 9. python reference integrity
function dottedPathExists(token) {
  // baro_core.a.b.c -> APP/a/b/c.py (or /c/__init__.py), allowing a trailing function name
  const parts = token.split(".");
  if (parts.shift() !== "baro_core") return true; // not ours to check
  if (!parts.length) return true; // the bare package
  let dir = APP;
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i];
    const asFile = path.join(dir, `${p}.py`);
    const asModule = path.join(dir, p, "__init__.py");
    if (fs.existsSync(asFile)) return i === parts.length - 1 || read(asFile).includes(`def ${parts[parts.length - 1]}`);
    if (fs.existsSync(asModule)) {
      dir = path.join(dir, p);
      if (i === parts.length - 1) return true; // the package itself
      continue;
    }
    return false;
  }
  return false;
}
{
  const problems = [];
  for (const p of pyFiles) {
    const src = read(p);
    for (const m of src.matchAll(/^\s*(?:from\s+(baro_core[\w.]*)\s+import|import\s+(baro_core[\w.]*))/gm)) {
      const token = m[1] || m[2];
      if (!dottedPathExists(token)) push(problems, `${rel(p)}: import ${token} does not resolve to a file`);
    }
    // hooks-style dotted callables
    for (const m of src.matchAll(/["'](baro_core\.[\w.]+)["']/g)) {
      if (!dottedPathExists(m[1])) push(problems, `${rel(p)}: referenced path ${m[1]} does not resolve`);
    }
    // BARO DocType names used in code
    for (const m of src.matchAll(/["'](Baro [A-Za-z ]+?)["']/g)) {
      const name = m[1];
      if (name.endsWith(" ") || name.includes("%")) continue;
      if (!doctypes.has(name)) push(problems, `${rel(p)}: DocType "${name}" is not defined in this app`);
    }
    // Indentation style, ignoring the inside of triple-quoted strings (SQL and docstrings are
    // free to be space-indented; code is not).
    let inString = false;
    let tabbed = false;
    let spaced = false;
    for (const line of src.split("\n")) {
      const quotes = (line.match(/"""/g) || []).length;
      if (!inString && /^\t+\S/.test(line)) tabbed = true;
      if (!inString && /^ {2,}\S/.test(line)) spaced = true;
      if (quotes % 2 === 1) inString = !inString;
    }
    if (tabbed && spaced) push(problems, `${rel(p)}: mixes tab and space indentation (docs/30: one style, diffable)`);
    // Crude but useful without a Python parser: unbalanced delimiters are always a real defect,
    // because string literals in this codebase keep their brackets paired.
    for (const [open, close] of [["(", ")"], ["[", "]"], ["{", "}"]]) {
      const o = src.split(open).length - 1;
      const c = src.split(close).length - 1;
      if (o !== c) push(problems, `${rel(p)}: ${o} "${open}" vs ${c} "${close}" - unbalanced`);
    }
    if (src.trim() && !src.endsWith("\n")) push(problems, `${rel(p)}: missing trailing newline`);
  }
  report("python imports, hook paths and DocType names resolve", problems);
}

// ---------------------------------------------------------------- 10. field-name integrity
{
  const defined = new Set();
  for (const [, dt] of doctypes) for (const f of dt.fields.keys()) defined.add(f);
  for (const row of fixture("custom_field")) defined.add(row.fieldname);
  const problems = [];
  const notes = [];
  const ALLOW = new Set(["baro_core"]);
  for (const m of read(path.join(APP, "modules.txt")).split("\n")) if (m.trim()) ALLOW.add(m.trim());
  for (const p of pyFiles) {
    const src = read(p);
    for (const m of src.matchAll(/\.(baro_[a-z0-9_]+)\b/g)) {
      if (!defined.has(m[1]) && !ALLOW.has(m[1])) push(problems, `${rel(p)}: .${m[1]} is not a field of any BARO DocType or custom field`);
    }
    for (const m of src.matchAll(/["'](baro_[a-z0-9_]+)["']\s*:/g)) {
      if (!defined.has(m[1]) && !ALLOW.has(m[1])) push(problems, `${rel(p)}: key "${m[1]}" is not a defined field`);
    }
    for (const m of src.matchAll(/\{\s*["'](baro_[a-z0-9_]+)["']/g)) {
      if (!defined.has(m[1])) notes.push(`${rel(p)}: filter ${m[1]}`);
    }
  }
  for (const wf of fixture("workflow")) {
    for (const m of JSON.stringify(wf).matchAll(/baro_[a-z0-9_]+/g)) {
      if (!defined.has(m[0])) push(problems, `workflow ${wf.name || wf.workflow_name}: ${m[0]} is not a defined field`);
    }
  }
  report("every baro_* field used in python and workflows is defined", problems);
}

// ---------------------------------------------------------------- 11. the automation boundary
{
  const problems = [];
  const boundaryFiles = [path.join(APP, "jobs.py")].concat(walk(path.join(APP, "integrations"), (p) => p.endsWith(".py")));
  for (const p of boundaryFiles) {
    const src = read(p);
    for (const m of src.matchAll(/\.submit\(\)|\.cancel\(\)|\.amend\(\)|frappe\.db\.set_value\([^)]{0,80}"docstatus"/g)) {
      push(problems, `${rel(p)}: "${m[0]}" lets a scheduled job perform a business action (docs/40 §1)`);
    }
    for (const m of src.matchAll(/frappe\.delete_doc\(\s*["']([^"']+)["']/g)) {
      if (!/Log$/.test(m[1])) push(problems, `${rel(p)}: deletes ${m[1]} from a job - only log records may be purged (docs/50 §11)`);
    }
  }
  // The UQ-DRV columns have exactly one writer (derive.set_active_keys) plus the documented
  // index-creation backfill patch (docs/31 §4.2, §7.1).
  for (const p of pyFiles) {
    const src = read(p);
    const r = rel(p);
    const exempt = r.endsWith("derive.py") || r.includes("patches/v1/");
    for (const m of src.matchAll(/(frappe\.db\.set_value\([^)]*baro_active_(?:serial|vehicle)_key|set\s+baro_active_(?:serial|vehicle)_key)/g)) {
      if (!exempt) push(problems, `${r}: writes a UQ-DRV column outside derive.py (${m[0].slice(0, 60)})`);
    }
  }
  report("detection is not action: no submit/cancel/ledger write in jobs or integrations", problems);
}

// ---------------------------------------------------------------- 12. scheduler catalog matches docs
{
  const problems = [];
  const hooks = read(path.join(APP, "hooks.py"));
  const jobNames = new Set();
  for (const m of hooks.matchAll(/["'](baro_core\.jobs\.([a-z_]+))["']/g)) jobNames.add(m[1]);
  const jobsSrc = read(path.join(APP, "jobs.py"));
  for (const name of jobNames) {
    const fn = name.split(".").pop();
    if (!new RegExp(`def ${fn}\\(`).test(jobsSrc)) push(problems, `hooks schedules ${name} but jobs.py has no such function`);
  }
  const doc60 = read(path.join(DOCS, "60-automation-trigger-catalog.md"));
  const docJobs = new Set([...doc60.matchAll(/`([a-z_]+(?:jobs\.)?[a-z_]+)`/g)].map((m) => m[1]));
  for (const m of hooks.matchAll(/baro_core\.jobs\.([a-z_]+)/g)) {
    if (!doc60.includes(`\`${m[1]}\``)) push(problems, `job ${m[1]} is scheduled but not named in docs/60 §3`);
  }
  for (const m of doc60.matchAll(/`(flag_[a-z_]+|sync_platform_fleet|process_integration_retries|run_platform_reconciliation|archive_integration_logs)`/g)) {
    if (!hooks.includes(`baro_core.jobs.${m[1]}`)) push(problems, `docs/60 names job ${m[1]} that hooks.py does not schedule`);
  }
  report("scheduled jobs and docs/60 §3 name each other", problems, [...docJobs].length ? [] : []);
}

// ---------------------------------------------------------------- 13. docs/10 field coverage
{
  const problems = [];
  const dd = path.join(DOCS, "10-data-dictionary.md");
  if (fs.existsSync(dd)) {
    const src = read(dd);
    const fields = new Set([...src.matchAll(/\|\s*`(baro_[a-z0-9_]+)`\s*\|/g)].map((m) => m[1]));
    const defined = new Set();
    for (const [, dt] of doctypes) for (const f of dt.fields.keys()) defined.add(f);
    for (const row of fixture("custom_field")) defined.add(row.fieldname);
    for (const f of fields) {
      if (!defined.has(f)) push(problems, `docs/10 §defines ${f} but no DocType field or custom field carries it`);
    }
  } else {
    push(problems, "docs/10-data-dictionary.md missing - coverage check skipped");
  }
  report("every field in the data dictionary exists in the schema", problems);
}

// ---------------------------------------------------------------- output
const width = Math.max(...checks.map((c) => c.name.length));
for (const c of checks) {
  const status = c.problems.length ? `FAIL (${c.problems.length})` : "ok";
  console.log(`${status.padEnd(12)} ${c.name}`);
  for (const p of c.problems.slice(0, verbose ? undefined : 12)) console.log(`      - ${p}`);
  if (!verbose && c.problems.length > 12) console.log(`      ... ${c.problems.length - 12} more (re-run with --verbose)`);
}
console.log(`\nchecks=${checks.length} failures=${failures}`);
process.exit(failures ? 1 : 0);
