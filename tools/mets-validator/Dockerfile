FROM eclipse-temurin:17-jdk-alpine AS builder

WORKDIR /app
COPY Validator.java .
RUN javac Validator.java

FROM eclipse-temurin:17-jre-alpine

WORKDIR /app
COPY --from=builder /app/*.class /app/

ENTRYPOINT ["java", "Validator"]
