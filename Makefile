REGISTRY ?= REGISTRY/aiops-quality-service
VERSION ?= $(shell cat VERSION)

build:
\tdocker build -f docker/Dockerfile.app -t $(REGISTRY):$(VERSION) .

push:
\tdocker push $(REGISTRY):$(VERSION)

helm-install:
\thelm upgrade --install aiops ./helm -n aiops --create-namespace

port:
\tkubectl -n aiops port-forward svc/aiops-quality-service 8000:8000

logs:
\tkubectl -n aiops logs -l app=aiops-quality-service -f
