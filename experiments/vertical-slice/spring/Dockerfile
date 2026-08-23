FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q dependency:go-offline
COPY src src
RUN mvn -q package -DskipTests
FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=build /src/target/vertical-slice-0.0.1-SNAPSHOT.jar app.jar
CMD ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
