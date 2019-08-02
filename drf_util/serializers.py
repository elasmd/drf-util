import copy

from django.core.paginator import Paginator, EmptyPage
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.fields import Field
from rest_framework.response import Response

from drf_util.exceptions import ValidationException
from drf_util.utils import any_value


class ElasticFilterSerializer(serializers.Serializer):
    sort_criteria = []
    default_filters = []

    def set_filters(self, filters):
        self.default_filters = filters

    def get_filter(self):
        es_filter = self.default_filters.copy()
        fields = self.get_fields()
        for field_name, field_instance in fields.items():
            call_attribute = 'filter_' + field_name
            if field_name in self.validated_data and hasattr(self, call_attribute):
                field_filter = getattr(self, call_attribute)(self.validated_data[field_name])
                es_filter.append(field_filter)
        return es_filter

    def get_fetched(self, results):
        for result in results:
            for field_name, field_value in result.items():
                if field_value:
                    call_attribute = 'fetch_' + field_name
                    if hasattr(self, call_attribute):
                        result[field_name] = getattr(self, call_attribute)(field_value, result)

        return results


class EmptySerializer(serializers.Serializer):
    pass


class IdSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class Fld(serializers.Field):
    def __init__(self, **kwargs):
        self.recursive_required = kwargs.pop('recursive_required', False)
        super(Fld, self).__init__(**kwargs)


class ChangebleSerializer(serializers.Serializer):
    # def to_internal_value(self, data):
    #     return data
    #
    # def to_representation(self, value):
    #     return value

    @staticmethod
    def set_recursive_required(field):
        if hasattr(field, 'fields'):
            for key, value in field.fields.items():
                if isinstance(value, Field) and not hasattr(field.fields[key], 'default'):
                    field.fields[key].required = True
                    ChangebleSerializer.set_recursive_required(field.fields[key])

    def update_properties(self, data):
        for key, value in data.items():
            if isinstance(value, Field):
                # if it's a custom Filed Class, then need to ignore default Field Class
                if key in self.fields and isinstance(value, Fld):
                    self.fields[key].required = value.required
                    if value.validators:
                        self.fields[key].validators = value.validators
                    if hasattr(value, 'input_formats'):
                        self.fields[key].input_formats = value.input_formats
                else:
                    self.fields[key] = value

                if hasattr(value, 'recursive_required') and value.recursive_required:
                    current_field = self.fields[key]
                    if hasattr(current_field, 'child'):
                        # it's list field
                        current_field = current_field.child
                    ChangebleSerializer.set_recursive_required(current_field.fields)
            else:
                if key not in self.fields:
                    if isinstance(value, list):
                        self.fields[key] = ChangebleSerializer(many=True)
                    else:
                        self.fields[key] = ChangebleSerializer()

                self.fields[key].required = True
                if isinstance(value, list):
                    self.fields[key].child.update_properties(any_value(value))
                else:
                    self.fields[key].update_properties(value)


class PaginatorSerializer(serializers.Serializer):
    page = serializers.IntegerField(default=1, min_value=1)
    per_page = serializers.IntegerField(default=50, min_value=1, required=False)

    default_per_page = 50

    pagination_remove_fields = ['page', 'per_page']

    def get_original_fields(self):
        data = copy.deepcopy(self.validated_data)
        for remove_field_key in self.pagination_remove_fields:
            try:
                del data[remove_field_key]
            except KeyError:
                pass
        return data

    def get_default_per_page(self):
        return self.data.get('per_page', self.default_per_page)

    def get_page(self):
        return self.data.get('page')

    def response(self, objects, per_page=None, serializer=None, context=None):
        objects, count = self.paginate_data(objects, per_page)
        return Response({
            'data': serializer(objects, many=True, context=context).data if serializer else objects,
            'total_results': count,
            'total': count,
            'per_page': self.get_default_per_page(),
            'page': self.get_page(),
        })

    def get_skip(self, per_page=None):
        size = per_page if per_page else self.get_default_per_page()
        page = self.get_page()
        skip = 0
        if int(page) > 1:
            skip = round(int(size) * int(page)) - int(size)
        return skip

    def paginate_data(self, objects, per_page=None):
        paginator = Paginator(objects, per_page if per_page else self.get_default_per_page())

        page = self.get_page()
        try:
            data = paginator.page(page)
        except EmptyPage:
            raise ValidationException({
                'page': [_('Page must be less than or equal to %s') % paginator.num_pages]
            })

        return data.object_list, data.paginator.count


class StringListField(serializers.ListField):
    child = serializers.CharField()
