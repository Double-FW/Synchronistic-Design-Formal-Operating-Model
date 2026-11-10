"""Export the approved Design Synchronicity Markdown without rewriting it."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import quote
import yaml
from jsonschema import Draft202012Validator
from synchronicity_hf_common import ROOT, SOURCE, MANAGED, destination, digest, git, load_config, read_sources

CONTEXT = ['AGENTS.md', 'README.md', 'Synchronistic_Design_Principles.md',
           'Synchronistic_Design_Formal_Operating_Model_v0.1.md']
MODEL_CONTEXT = ['Synchronistic_Design_Formal_Operating_Model_v0.1.md#10-controlled-states',
                 'Synchronistic_Design_Formal_Operating_Model_v0.1.md#11-decision-rights-and-escalation',
                 'Synchronistic_Design_Formal_Operating_Model_v0.1.md#12-role-of-an-llm-or-agentic-system']

def metadata(text):
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', text, re.S)
    md = yaml.safe_load(match[1]) if match else {}
    return md if isinstance(md, dict) else {}

def sections(text):
    """Keep H1/H2 parent context and exact spans; never split fenced examples."""
    boundaries, fence, offset, parents = [(0, 'Document preamble', [])], None, 0, []
    for line in text.splitlines(keepends=True):
        mark = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if mark:
            token = mark[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[mark.end():].strip():
                fence = None
        elif fence is None:
            match = re.match(r'^(#{1,2})[ \t]+([^\r\n]+)', line)
            if match:
                level, title = len(match[1]), match[2].strip().rstrip('#').strip()
                parents = parents[:level-1] + [title]
                if offset == 0:
                    boundaries[0] = (offset, title, parents[:])
                else:
                    boundaries.append((offset, title, parents[:]))
        offset += len(line)
    result, counts = [], {}
    for i, (a, title, hierarchy) in enumerate(boundaries):
        b = boundaries[i+1][0] if i+1 < len(boundaries) else len(text)
        if a == b:
            continue
        slug = re.sub(r'[^a-z0-9]+', '-', ' '.join(hierarchy or [title]).lower()).strip('-') or 'section'
        counts[slug] = counts.get(slug, 0) + 1
        key = slug if counts[slug] == 1 else slug + '-' + str(counts[slug])
        result.append((key, title, text[a:b], a, b, hierarchy))
    if ''.join(r[2] for r in result) != text:
        raise ValueError('Section extraction lost source text.')
    return result

def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output == root or root in output.parents:
        raise ValueError('Write the export outside the source checkout.')
    cfg = load_config(root)
    target = destination(cfg['destination_dataset'])
    texts, manifest, omitted = read_sources(root, cfg)
    sha = git(root, 'rev-parse', 'HEAD').decode().strip()
    date = git(root, 'show', '-s', '--format=%cs', 'HEAD').decode().strip()
    warnings = ['This is an implementation-agnostic high-level draft model, not a deployed agent, adopted organisational process, certification scheme or completed experience evaluation.']
    if 'Intent → Context → Sensemaking → Orchestration → Action → Feedback → Synchronization' in texts['README.md'] and 'continuous six-part reasoning cycle' in texts[cfg['model_file']]:
        warnings.append('The README/agent framing uses a seven-part Intent-to-Synchronization cycle; the formal model describes six Orient-to-Learn activities. Both source descriptions are preserved without silently harmonising them.')
    if 'not public' in texts['README.md']:
        warnings.append('The source README says some specialist repositories are not public. References are preserved; no access, public availability, integration or deployed dependency is inferred.')
    introductions = {path: sections(text)[0][2] if text else '' for path, text in texts.items()}
    def row(path, key, title, body, a, b, hierarchy, kind):
        md = metadata(texts[path])
        version_status = re.search(r'^## (Version [^\n]+)', texts[path], re.M)
        return {'id': path + '::' + key, 'title': title, 'text': body, 'record_type': kind,
            'source_repository': SOURCE, 'source_path': path, 'source_commit': sha,
            'source_url': f'https://github.com/{SOURCE}/blob/{sha}/{quote(path)}',
            'source_start_line': texts[path][:a].count('\n') + 1,
            'source_end_line': max(1, texts[path][:b].count('\n') + (not texts[path][:b].endswith('\n'))),
            'source_document_sha256': digest(texts[path].encode()), 'text_sha256': digest(body.encode()),
            'heading_path': hierarchy, 'metadata_json': json.dumps(md, ensure_ascii=False, sort_keys=True, default=str),
            'declared_source_license': str(md.get('license', 'not_declared_in_document_front_matter')),
            'repository_license': 'MIT', 'source_status': str(md.get('status', version_status[1] if version_status else 'see_source')),
            'source_document_intro': introductions[path], 'required_context_sections': MODEL_CONTEXT,
            'dataset_version': cfg['dataset_version'], 'source_commit_date': date, 'language': 'en-GB',
            'required_context_paths': list(dict.fromkeys([path] + [p for p in CONTEXT if p in texts])),
            'review_status': 'faithful_extraction_checked_not_model_implementation_or_outcome_validation'}
    docs, chunks = [], []
    for path in cfg['files']:
        if path not in texts:
            continue
        text = texts[path]
        kind = ('agent_governance_guidance' if path == 'AGENTS.md' else
                'orientation_and_operating_framing' if path == 'README.md' else
                'human_centred_design_principles' if path == 'Synchronistic_Design_Principles.md' else
                'high_level_draft_operating_model_not_implementation')
        docs.append(row(path, 'document', path, text, 0, len(text), [], kind))
        for key, title, body, a, b, hierarchy in sections(text):
            section_kind = ('evidence_state_definitions_not_assigned_results' if path == cfg['model_file'] and title == '10. Controlled states' else
                            'human_decision_rights_and_escalation_guidance' if path == cfg['model_file'] and title == '11. Decision rights and escalation' else
                            'agent_role_and_authority_limits' if path == cfg['model_file'] and title == '12. Role of an LLM or agentic system' else kind)
            chunks.append(row(path, key, title, body, a, b, hierarchy, section_kind))
    if not docs or not chunks:
        raise ValueError('The guidance export is empty.')
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object',
              'required': list(docs[0]), 'additionalProperties': False, 'properties': {}}
    for k, v in docs[0].items():
        schema['properties'][k] = {'type': 'array', 'items': {'type': 'string'}} if isinstance(v, list) else {'type': 'integer' if isinstance(v, int) else 'string'}
    validator = Draft202012Validator(schema)
    for records in (docs, chunks):
        if len({r['id'] for r in records}) != len(records):
            raise ValueError('Duplicate export identifiers.')
        for r in records:
            validator.validate(r)
            if digest(r['text'].encode()) != r['text_sha256']:
                raise ValueError('Text checksum mismatch.')
    output.mkdir(parents=True, exist_ok=True)
    def write_json(name, obj):
        (output/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name, records in [('documents.jsonl', docs), ('knowledge_chunks.jsonl', chunks)]:
        (output/name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    (output/'LICENSE').write_bytes(texts['LICENSE'].encode())
    write_json('record_schema.json', schema)
    write_json('provenance.json', {'source_repository': SOURCE, 'source_commit': sha, 'source_commit_date': date,
        'destination_dataset': target, 'dataset_version': cfg['dataset_version'], 'files': manifest,
        'omitted_optional_files': omitted, 'source_warnings': warnings, 'external_sources_fetched': False})
    source_notice = '\n'.join('- '+w for w in warnings)
    card = f'''---
pretty_name: Double FW Design Synchronicity
language:
- en
license: mit
tags:
- accessibility
- inclusive-design
- service-design
- organisational-governance
- agent-governance
- text
configs:
- config_name: knowledge_chunks
  default: true
  data_files:
  - split: train
    path: knowledge_chunks.jsonl
- config_name: documents
  data_files:
  - split: train
    path: documents.jsonl
---

# Double FW Design Synchronicity

The Synchronistic Design principles and high-level formal operating model from Double FW Ltd. It connects organisational promise, human intention/context, product/service capabilities, interaction behaviour, evidence and accountable decisions. This is an adaptable reasoning/orchestration model, not a prescribed design system, delivery lifecycle, implemented agent, live governance service or compliance certification.

## Source and versions

Source: https://github.com/{SOURCE}

Source revision: `{sha}`. Commit date: {date}. Export format: {cfg['dataset_version']}. The formal model remains version 0.1, a high-level draft. Publication does not establish organisational adoption, implementation, independent model validation, user research, approval or proven equivalent experience.

## Dataset views

- `knowledge_chunks` (default): {len(chunks)} exact Markdown sections, with parent headings, fenced diagrams, tables, qualifications and deeper subsections retained.
- `documents`: {len(docs)} complete source documents: AGENTS.md, README.md, Synchronistic_Design_Principles.md and Synchronistic_Design_Formal_Operating_Model_v0.1.md.

The views overlap. Do not concatenate them blindly. The `train` split is a loading convention. No generated question/answer pairs, model fine-tuning, benchmark/evaluation split, case records or implemented workflow specifications are supplied. Hypothetical examples and suggested reasoning-record fields remain proposals, not evidence that research, decisions or deployments occurred.

## Source variation and connected resources

{source_notice}

The README, principles and AGENTS.md have their own framing and principle lists. The export retains their wording and context rather than renumbering, merging or deciding their equivalence. Future source edits may change the relationships. Confirm the intended framing for a real adoption with an authorised owner.

Specialist repository references describe potential capabilities and routing relationships, not verified integrations or guaranteed public access. This exporter does not fetch or mirror external content, grant access, repair source links or revalidate their availability. Keep specialist knowledge and attribution in its owning source.

## Evidence, states and authority

Read all four source documents as relevant, particularly the formal model's sections 10 (controlled states), 11 (decision rights) and 12 (LLM/agent role). Every row carries context paths and section references; they are retrieval references rather than enforced runtime controls or tool permissions. Complete-document rows provide full interpretation context.

The controlled states are definitions for evidence/governance use: Supported, Partially supported, Unsupported, Contradicted, Not assessed, Customer evidence required, Human decision required and Exception active. The relevant section is labelled evidence_state_definitions_not_assigned_results. Exporting these terms does not assign them to a real claim, approve an exception or establish certification. Human decision rights and agent limits are separately labelled source sections; their text remains intact.

A successful task, automated check, standards pass or synthetic persona alone does not demonstrate lived experience or equivalent outcomes. Preserve uncertainty, dissent, trade-offs and evidence gaps. Do not invent human intentions, research, policies, risk owners, approvals or available capabilities. Recommendations, evidence production and accountable decisions remain distinct. Model guidance does not grant permission to contact people, collect data, publish external claims, deploy, override authorised decisions, approve policy/exception decisions or accept risk.

## Extraction, schema and provenance

Normal Markdown is split at first/second-level headings outside fenced blocks. Third-level decision roles, cycle activities and supporting explanations remain with their owning section. Text is preserved exactly, including diagrams and limitations. A renamed heading may change its section identifier. Source cycle descriptions are preserved, not transformed into executable control logic.

Rows include exact source path/commit/URL, line ranges, text and full-document SHA-256 hashes, heading path, JSON-encoded front matter, source status/licence, original introduction and context paths/sections. `see_source` means no explicit status was extracted from front matter or the version heading; it is not approval. Use text for the exact record span; the introduction is repeated context. Resolve relative/fragment links against the immutable source URL. See record_schema.json and provenance.json.

## Privacy and licence

Only explicitly approved committed public documents are read. No live personal, disability, employee or confidential organisational dataset is supplied. New or renamed source files need review and inclusion in huggingface/export-config.json. Confidential content inserted into an approved source is not detected automatically; review public commits and keep real evidence in approved systems.

The root MIT LICENSE is copied unchanged, including copyright (c) 2026 Double FW. Source attribution/notices remain intact. Linked material retains its own rights and is not copied or relicensed. Packaging is not an independent rights, legal, security or outcome assessment.

## Updates

GitHub is the authoring source. Updates are configured for Mondays at 07:23 UTC and manual runs. GitHub may delay schedules or disable them after inactivity. All four Markdown documents and LICENSE are required; missing context, changed licence, invalid configuration or failed integrity checks stop publication.

Only README.md, LICENSE, documents.jsonl, knowledge_chunks.jsonl, provenance.json, record_schema.json and validation_report.json are managed. Other raw files and .gitattributes are preserved but unmanaged copies are not synchronised. Visibility is unchanged. Updates use one commit guarded by the destination revision. Historical revisions and downloads are not recalled. Initial authenticated publication must still be checked.

## Loading

```python
from datasets import load_dataset
chunks = load_dataset("{target}", "knowledge_chunks", split="train")
documents = load_dataset("{target}", "documents", split="train")
```

Private datasets require authentication. Pin a destination revision for reproducibility. Loading rows does not implement orchestration, governance or approval enforcement.
'''
    yaml.safe_load(card.split('---', 2)[1])
    (output/'README.md').write_text(card, encoding='utf-8')
    report = {'status': 'passed', 'scope': 'faithful extraction and packaging checks only', 'source_commit': sha,
        'source_files_verified': len(manifest), 'document_records': len(docs), 'knowledge_section_records': len(chunks),
        'source_warnings': warnings, 'independent_content_review': False, 'live_publication_tested': False,
        'export_file_sha256': {name: digest((output/name).read_bytes()) for name in MANAGED if name != 'validation_report.json'}}
    write_json('validation_report.json', report)
    return report

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(ROOT, args.output)))

if __name__ == '__main__':
    main()
