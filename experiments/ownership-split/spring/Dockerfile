FROM maven:3.9.11-eclipse-temurin-25 AS build
WORKDIR /src
COPY pom.xml .
COPY src src
RUN mvn -q -DskipTests package
FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=build /src/target/ownership-split-0.0.1-SNAPSHOT.jar app.jar
CMD ["java", "-Xms128m", "-Xmx512m", "-jar", "app.jar"]
