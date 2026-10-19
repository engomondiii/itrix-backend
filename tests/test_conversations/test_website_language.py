"""The website's selected language reaches the existing conversation engine."""
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient
from apps.conversations.models import Thread

pytestmark = pytest.mark.django_db


def test_selected_language_is_saved_before_generation(settings):
    settings.ENABLE_CONVERSATION_SURFACE = True
    api = APIClient()
    with patch('apps.conversations.views_thread._attempt_assistant_generation') as generate:
        generate.return_value.turn = None
        generate.return_value.state = 'disabled'
        response = api.post('/api/v1/threads/', {'body': 'Explain ASTOP', 'locale': 'ko'}, format='json')
        assert response.status_code == 201
        thread = Thread.objects.get(id=response.json()['threadId'])
        assert thread.locale == 'ko'
        assert generate.call_args.args[0].locale == 'ko'
        response = api.post(f'/api/v1/threads/{thread.id}/turns/', {'body': 'What is next?', 'locale': 'en'}, format='json')
        assert response.status_code == 201
        thread.refresh_from_db()
        assert thread.locale == 'en'
        assert generate.call_args.args[0].locale == 'en'


def test_unknown_language_rejected(settings):
    settings.ENABLE_CONVERSATION_SURFACE = True
    response = APIClient().post('/api/v1/threads/', {'locale': 'arbitrary instruction'}, format='json')
    assert response.status_code == 400
    assert not Thread.objects.exists()
