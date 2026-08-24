FROM maven:3.9.11-eclipse-temurin-25 AS build
WORKDIR /workspace
COPY spring/vertical-slice/pom.xml spring/vertical-slice/pom.xml
RUN mvn -B -f spring/vertical-slice/pom.xml dependency:go-offline
COPY spring/vertical-slice/src spring/vertical-slice/src
RUN mvn -B -f spring/vertical-slice/pom.xml package -DskipTests

FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=build /workspace/spring/vertical-slice/target/brainnet-spring-vertical-slice-0.1.0-SNAPSHOT.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-Xms128m", "-Xmx512m", "-jar", "/app/app.jar"]
