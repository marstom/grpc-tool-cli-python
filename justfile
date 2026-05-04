set shell := ["bash", "-cu"]

grpc:
    BASE_PROTO="/home/tomasz/zego/protobuf/proto"; \
    python -m grpc_tools.protoc \
        -I "$BASE_PROTO" \
        --python_out=. \
        --grpc_python_out=. \
        $(find "$BASE_PROTO" -name "*.proto")


grpcui:
    grpcui -port 8888 \
    -import-path /home/tomasz/zego/protobuf/proto \
    -proto /home/tomasz/zego/protobuf/proto/zego/grpc/quotes/v1/quote.proto \
    quotes.staging-aws.zegocover.com:443


grpcui_collection:
    grpcui -port 8888 \
    -examples ~/Downloads/hist1.jsona \
    -import-path /home/tomasz/zego/protobuf/proto \
    -proto /home/tomasz/zego/protobuf/proto/zego/grpc/quotes/v1/quote.proto \
    quotes.staging-aws.zegocover.com:443

