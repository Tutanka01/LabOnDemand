export function createDashboardState() {
    return {
        labCounter: 0,
        novncEndpoints: new Map(),
        lastLaunchedDeployment: null,
        currentStatusDeployment: null,
        cachedPvcs: [],
        pvcsLastFetched: 0,
        cachedAdminPvcs: [],
        adminPvcsLastFetched: 0,
        lastQuotaData: null,
        deploymentCheckTimers: new Map(),
    };
}
