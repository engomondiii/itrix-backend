"""Import exact October originals into private storage using the reviewed hash inventory.

Nothing is uploaded or embedded. Originals default to internal-only; patent specifications
are prohibited from embedding. Public summaries remain the visitor-facing sources.
"""
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.knowledge_core.models import KnowledgeDocument


class Command(BaseCommand):
    help = 'Register exact approved October archive bytes in private storage (no embeddings).'
    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True)
        parser.add_argument('--storage-root', required=True)
        parser.add_argument('--dry-run', action='store_true')
    def handle(self, *args, **options):
        root = Path(options['storage_root']).resolve()
        repo = Path(settings.BASE_DIR).resolve()
        if root == repo or repo in root.parents:
            raise CommandError('Private originals must be stored outside the Git checkout.')
        catalog = json.loads((repo / 'docs/source_alignment_20261003.json').read_text())
        expected = {r['sha256']: r for r in catalog['records'] if r['group'] == 'new'
            and Path(r['source']).suffix.lower() in {'.docx', '.pdf', '.pptx', '.txt'}
            and r['source'] not in {'README_KO.txt', 'SHA256SUMS.txt'}}
        found = {}
        total = 0
        def walk(data, depth=0):
            nonlocal total
            if depth > 2:
                raise CommandError('Unexpected archive nesting.')
            with ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if info.is_dir() or '__MACOSX' in info.filename or Path(info.filename).name.startswith('._'):
                        continue
                    if info.file_size > 100 * 1024 * 1024:
                        raise CommandError('Archive member exceeds size limit.')
                    total += info.file_size
                    if total > 512 * 1024 * 1024:
                        raise CommandError('Archive exceeds expanded size limit.')
                    content = archive.read(info)
                    hash_value = hashlib.sha256(content).hexdigest()
                    if hash_value in expected:
                        found[hash_value] = content
                    if info.filename.lower().endswith('.zip'):
                        walk(content, depth + 1)
        walk(Path(options['archive']).read_bytes())
        missing = set(expected) - set(found)
        if missing:
            raise CommandError(f'Archive is missing {len(missing)} exact approved sources; no registration performed.')
        with transaction.atomic():
            for hash_value, content in sorted(found.items()):
                source = expected[hash_value]
                suffix = Path(source['source']).suffix.lower()
                # PPTX is an undecided strategy deck, not supported by the RAG loader.
                prohibited = 'Restricted original' in source['disposition'] or suffix == '.pptx'
                disclosure = 'prohibited' if prohibited else 'internal_only'
                destination = root / (hash_value + suffix)
                if options['dry_run']:
                    self.stdout.write(f'{disclosure}: {source["source"]}')
                    continue
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                if destination.is_symlink():
                    raise CommandError('Private destination must not be a symlink.')
                if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != hash_value:
                    raise CommandError('Private destination content mismatch.')
                destination.write_bytes(content)
                destination.chmod(0o600)
                # Original corpus is internal reference evidence, not a second public authority.
                namespace = 'astop' if 'ASTOP' in source['source'].upper() else 'technology'
                if 'Portfolio' in source['source']:
                    namespace = 'company'
                KnowledgeDocument.objects.update_or_create(file_path=str(destination), defaults={
                    'title': source['source'], 'namespace': namespace, 'disclosure_level': disclosure,
                    'is_current': not prohibited, 'source_authority': 'working',
                    'canonical_rule': ('Exact October source retained privately. Public summaries govern public answers. '
                        'No patent identifiers, addresses, confidential strategy or protected mechanisms may be externalized.'),
                    'permitted_paraphrase': 'none', 'ingestion_status': 'COMPLETE' if prohibited else 'PENDING',
                })
        self.stdout.write(self.style.SUCCESS(f'{"Verified" if options["dry_run"] else "Registered"} {len(found)} exact originals. No embeddings or public release performed.'))
