from rest_framework import serializers
from .models import JourneyDecision


class JourneyDecisionInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=JourneyDecision.OUTCOMES)
    workload = serializers.CharField(max_length=200)
    comparable = serializers.BooleanField(default=False)
    fidelity = serializers.ChoiceField(choices=['preserved', 'failed', 'unknown'])
    net_value = serializers.ChoiceField(choices=['positive', 'nonpositive', 'unknown'])
    measured_results = serializers.CharField(max_length=4000, allow_blank=True, required=False, default='')
    qualitative_feedback = serializers.CharField(max_length=4000)

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('Unsupported decision fields.')
        return attrs

