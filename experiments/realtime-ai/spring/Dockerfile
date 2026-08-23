FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -DskipTests dependency:go-offline
COPY src src
RUN mvn -q test package

FROM eclipse-temurin:25-jre-alpine
WORKDIR /app
COPY --from=build /src/target/realtime-ai-0.0.1-SNAPSHOT.jar app.jar
CMD ["java", "-jar", "app.jar"]
