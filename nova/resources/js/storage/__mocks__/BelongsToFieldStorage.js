const resources = [{ value: 1 }, { value: 2 }, { value: 3 }]

const softDeleteTypes = {
    users: true,
    authors: false,
}

export default {
    fetchAvailableResources(resourceName, fieldAttribute, { params }) {
        return new Promise((resolve, reject) => {
            if (params.first == true) {
                resolve({
                    data: {
                        resources: [resources[params.current - 1]],
                        withTrashed: true,
                        softDeletes: true,
                    },
                })
            }

            return resolve({
                data: {
                    resources,
                    withTrashed: true,
                    softDeletes: true,
                },
            })
        })
    },

    determineIfSoftDeletes(resourceName) {
        return new Promise((resolve, reject) => {
            resolve({
                data: {
                    softDeletes: softDeleteTypes[resourceName],
                },
            })
        })
    },
}
