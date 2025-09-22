from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from arkumu.users.models import User

from .serializers import UserSerializer


class UserViewSet(GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.none()
    http_method_names = ["get"]

    @action(detail=False, methods=["get"], url_path="me", url_name="me")
    def me(self, request):
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(status=status.HTTP_200_OK, data=serializer.data)
