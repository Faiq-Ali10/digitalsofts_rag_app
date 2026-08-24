# Digitalsofts — Technical FAQ

## API and Integration

### How do I access the API?
All Digitalsofts products provide a RESTful API. API access requires an API key which can be generated from the administration panel. API documentation is available at https://docs.digitalsofts.com/api.

### What authentication methods does the API support?
- **API Key**: For server-to-server integrations
- **OAuth 2.0**: For third-party application integrations
- **JWT**: For user-level authentication in web and mobile applications

### Is there a rate limit on the API?
Yes, API rate limits depend on your subscription tier:
- **Standard**: 100 requests/minute
- **Professional**: 500 requests/minute
- **Enterprise**: 2000 requests/minute (or custom)

## Data and Migration

### How is data migration handled?
We provide a structured data migration process:
1. Data mapping template provided by our team
2. Customer fills the template with existing data
3. Test migration performed in a staging environment
4. Customer validates migrated data
5. Final migration during go-live

### What data formats are supported for import?
- CSV (recommended)
- Excel (.xlsx)
- JSON
- XML
- Direct database migration (for enterprise clients)

### Can I export my data?
Yes, you can export your data at any time:
- Standard reports can be exported to Excel, PDF, and CSV
- Full database export available on request
- API access for programmatic data extraction
- Data retention: All data is retained for the duration of the subscription plus 90 days after cancellation

## Deployment and Infrastructure

### What are the system requirements for on-premise deployment?
Minimum requirements:
- **Server**: 4 CPU cores, 16 GB RAM, 500 GB SSD
- **OS**: Ubuntu 22.04 LTS or RHEL 8+
- **Database**: PostgreSQL 14+
- **Runtime**: Docker and Docker Compose
- **Network**: HTTPS with valid SSL certificate

### How are updates and patches handled?
- **Cloud (SaaS)**: Updates are applied automatically during maintenance windows
- **On-premise**: Update packages are provided monthly with release notes. Customers schedule their own update windows.

### Is disaster recovery included?
- **Cloud**: Automated backups, multi-AZ deployment, and tested DR procedures
- **On-premise**: Backup scripts and DR documentation provided. Customer manages DR infrastructure.
