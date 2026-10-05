import hashlib
import json
from io import BytesIO
from zipfile import ZipFile
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.knowledge_core.models import KnowledgeDocument

pytestmark=pytest.mark.django_db


def archive_fixture(tmp_path,settings):
    repo=tmp_path/'repo';(repo/'docs').mkdir(parents=True)
    settings.BASE_DIR=repo
    raw=b'exact original test bytes'
    sha=hashlib.sha256(raw).hexdigest()
    (repo/'docs/source_alignment_20261003.json').write_text(json.dumps({'records':[
        {'group':'new','source':'test.pdf','sha256':sha,'disposition':'Restricted original; no public import'}]}))
    archive=tmp_path/'new.zip'
    with ZipFile(archive,'w') as z:z.writestr('../../test.pdf',raw)
    return archive,raw,sha,repo


def test_exact_private_import_is_hash_named_prohibited_and_idempotent(tmp_path,settings):
    archive,raw,sha,repo=archive_fixture(tmp_path,settings)
    dest=tmp_path/'private'
    call_command('import_october_sources',archive=str(archive),storage_root=str(dest),dry_run=True)
    assert not dest.exists() and not KnowledgeDocument.objects.exists()
    for _ in range(2):call_command('import_october_sources',archive=str(archive),storage_root=str(dest))
    assert (dest/(sha+'.pdf')).read_bytes()==raw
    assert not (tmp_path/'test.pdf').exists()
    assert KnowledgeDocument.objects.count()==1
    assert KnowledgeDocument.objects.get().disclosure_level=='prohibited'
    assert KnowledgeDocument.objects.get().is_current is False


def test_import_rejects_checkout_destination_and_incomplete_archive(tmp_path,settings):
    archive,raw,sha,repo=archive_fixture(tmp_path,settings)
    with pytest.raises(CommandError):call_command('import_october_sources',archive=str(archive),storage_root=str(repo/'sources'))
    with ZipFile(archive,'w') as z:z.writestr('test.pdf',b'altered')
    with pytest.raises(CommandError):call_command('import_october_sources',archive=str(archive),storage_root=str(tmp_path/'private'))
    assert not KnowledgeDocument.objects.exists()


def test_validator_requires_october_sources_and_rejects_reactivated_old_canonical(settings):
    from io import StringIO
    from apps.knowledge_core.models import KnowledgeChunk
    settings.ENABLE_AI_ENGINE=False
    settings.PINECONE_API_KEY=''
    for filename,tier,authority,namespace in (
        ('itrix_product_portfolio_v1_4.md','public','authoritative','company'),
        ('astop_product_and_access_20261002.md','public','authoritative','astop'),
        ('research_portfolio_summary_20261002.md','public','governing','technology'),
        ('platform_governance_current_20261003.md','internal_only','governing','company'),
        ('astop_customer_journey_v1_5.md','public','governing','astop'),
        ('astop_license_order_summary_v2_6.md','public','governing','astop'),
        ('astop_branch_program_summary_v1_4.md','public','governing','astop'),
        ('astop_comparison_current_20261003.md','public','authoritative','astop'),
        ('astop_activation_policy_20261004.md','internal_only','governing','astop'),
        ('research_evidence_register_20261003.md','controlled_public','governing','technology'),
    ):
        doc=KnowledgeDocument.objects.create(title=filename,file_path=f'knowledge_docs/{tier}/{filename}',
            namespace=namespace,disclosure_level=tier,source_authority=authority,is_current=True,
            ingestion_status='COMPLETE',chunk_count=1)
        KnowledgeChunk.objects.create(document=doc,chunk_index=0,text='Curated evidence.',namespace=namespace,vector_id=filename)
    out=StringIO()
    call_command('validate_knowledge_core',stdout=out)
    assert 'Knowledge Core validation passed' in out.getvalue()
    KnowledgeDocument.objects.create(title='old',file_path='knowledge_docs/public/itrix_product_canonical_v3_5.md',
        namespace='company',disclosure_level='public',source_authority='legacy',is_current=True)
    with pytest.raises(SystemExit):call_command('validate_knowledge_core',stdout=StringIO())


def test_catalogue_validator_keeps_adjacent_technology_statement_separate():
    from apps.knowledge_core.management.commands.validate_knowledge_core import current_public_conflicts
    assert not current_public_conflicts(
        "Current products are ASTOP, AXIOM Compute, AXIOM Core and QNTA Runtime. "
        "CRE is enabling technology; FQNM and SPADES are research assets.")
    assert "technology classified as sold product" in current_public_conflicts("Our products are CRE and FQNM.")
