"""Serializers for notes and the activity timeline."""

from rest_framework import serializers

from apps.core import attachments

from .models import Activity, Note


class AuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class NoteSerializer(serializers.ModelSerializer):
    author = AuthorSerializer(read_only=True)
    target = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = ["id", "body", "author", "target", "created_at", "updated_at"]

    def get_target(self, obj):
        slug = attachments.slug_for_model(obj.content_type.model_class())
        return {"content_type": slug, "object_id": obj.object_id}


class NoteCreateSerializer(serializers.Serializer):
    """POST body: {body, content_type: "client", object_id: 7}."""

    body = serializers.CharField()
    content_type = serializers.ChoiceField(choices=attachments.attachable_slugs())
    object_id = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        target = attachments.get_visible_target(
            attrs["content_type"], attrs["object_id"], user=self.context["request"].user
        )
        if target is None:
            raise serializers.ValidationError(
                {"object_id": f"No {attrs['content_type']} with id {attrs['object_id']}."}
            )
        attrs["target"] = target
        return attrs

    def create(self, validated_data):
        return Note.objects.create(
            body=validated_data["body"],
            author=self.context["request"].user,
            content_object=validated_data["target"],
        )


class NoteUpdateSerializer(serializers.ModelSerializer):
    """PATCH may change the text only — never re-pin a note to another object."""

    class Meta:
        model = Note
        fields = ["body"]


class ActivitySerializer(serializers.ModelSerializer):
    """
    Read-only timeline row. There is NO write serializer on purpose:
    activities are created exclusively by services.record() inside business
    services — an audit trail the API could write to would be worthless.
    """

    actor = AuthorSerializer(read_only=True)
    target = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = ["id", "verb", "changes", "actor", "target", "created_at"]
        read_only_fields = fields

    def get_target(self, obj):
        slug = attachments.slug_for_model(obj.content_type.model_class())
        return {"content_type": slug, "object_id": obj.object_id}
