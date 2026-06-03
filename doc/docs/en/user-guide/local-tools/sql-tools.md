---
title: SQL Database Tools
---

# SQL Database Tools

The SQL database toolset enables AI agents to connect to and query relational databases such as MySQL, PostgreSQL, and SQL Server, allowing direct data access and manipulation.

## Tool List

- `mysql_database`: Connect to MySQL and execute SQL queries
- `postgres_database`: Connect to PostgreSQL and execute SQL queries
- `mssql_database`: Connect to SQL Server and execute SQL queries

## Usage Scenarios

- Query report data from business databases for agent analysis and summarization
- Cross-database joins to retrieve related information scattered across multiple tables
- Real-time queries of business status to provide agents with up-to-date data

## Parameters and Behavior

### Common Parameters

- `sql`: The SQL query to execute (required)
- `parameters`: Parameter values for parameterized queries (optional)
- `max_rows`: Maximum number of rows to return (default: 100)
- `timeout`: Query timeout in seconds (default: 10)

### Database Connection Parameters

| Database    | Connection Parameters                                                      |
|-------------|---------------------------------------------------------------------------|
| MySQL       | `host`, `user`, `password`, `database`, `port` (default 3306)             |
| PostgreSQL  | `host`, `user`, `password`, `database`, `port` (default 5432)             |
| SQL Server  | `host`, `user`, `password`, `database`, `port` (default 1433)            |

### Security Restrictions

- Forbidden operations: `DROP DATABASE`, `GRANT`, `REVOKE`, `CREATE USER`, `INTO OUTFILE`, `LOAD DATA INFILE`
- `UPDATE` and `DELETE` statements must include a `WHERE` clause
- `LIMIT` is automatically added to restrict returned rows

### Response Format

```json
{
  "status": "success",
  "columns": ["id", "name", "email"],
  "rows": [[1, "John Doe", "john@example.com"]],
  "row_count": 1,
  "execution_time_ms": 45.23
}
```

## Getting Started

1. **Prepare connection info**: Obtain host address, port, database name, username, and password
2. **Configure the tool**: Add the appropriate database tool in agent configuration and fill in connection parameters
3. **Test connection**: Use a simple query to verify connectivity
4. **Construct queries**: Let the agent understand natural language requirements and generate corresponding SQL

## Security Best Practices

- Use read-only accounts in production to limit operation permissions
- Store sensitive information like database passwords in a key management service
- Set reasonable `max_rows` values to avoid returning excessive data at once
- Enable SSL/TLS encryption for database connections

## Common Database Connection Examples

| Database    | Connection Example | Parameter Placeholder |
|-------------|-------------------|---------------------|
| MySQL       | `localhost:3306`  | `?`                 |
| PostgreSQL  | `localhost:5432`  | `$1, $2, ...`       |
| SQL Server  | `localhost:1433`  | `?`                 |

> Note: Different databases use different parameter placeholder formats. PostgreSQL uses `$1, $2`, while others use `?`.
