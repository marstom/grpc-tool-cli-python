set shell := ["bash", "-cu"]

grpc:
    BASE_PROTO="/home/tomasz/zego/protobuf/proto"; \
    python -m grpc_tools.protoc \
        -I "$BASE_PROTO" \
        --python_out=. \
        --grpc_python_out=. \
        $(find "$BASE_PROTO" -name "*.proto")
