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
